from datetime import datetime, timezone
from sqlalchemy import text
from .db import engine


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _upsert_team(conn, provider, provider_team_id, name, country=None):
    alias = conn.execute(text("SELECT team_id FROM team_aliases WHERE provider=:p AND provider_team_id=:pid"),
                         {"p": provider, "pid": str(provider_team_id)}).fetchone()
    if alias:
        return alias[0]
    row = conn.execute(text("SELECT id FROM teams WHERE provider=:p AND provider_team_id=:pid"),
                       {"p": provider, "pid": str(provider_team_id)}).fetchone()
    if row:
        conn.execute(text("UPDATE teams SET name=:n, country=COALESCE(:c,country) WHERE id=:id"),
                     {"n": name, "c": country, "id": row[0]})
        return row[0]
    # Preserve one canonical team row when the provider's name already exists.
    canonical = conn.execute(text("SELECT id FROM teams WHERE lower(name)=lower(:n) LIMIT 1"), {"n": name}).fetchone()
    if canonical:
        team_id = canonical[0]
        conn.execute(text("INSERT OR IGNORE INTO team_aliases(team_id,provider,provider_team_id,provider_name) VALUES(:t,:p,:pid,:n)"),
                     {"t": team_id, "p": provider, "pid": str(provider_team_id), "n": name})
        return team_id
    return conn.execute(text("INSERT INTO teams(provider,provider_team_id,name,country) VALUES(:p,:pid,:n,:c)"),
                        {"p": provider, "pid": str(provider_team_id), "n": name, "c": country}).lastrowid


def _upsert_competition(conn, provider, provider_comp_id, name, country, season):
    row = conn.execute(text("SELECT id FROM competitions WHERE provider=:p AND provider_competition_id=:pid AND COALESCE(season,'')=COALESCE(:s,'')"),
                       {"p": provider, "pid": str(provider_comp_id), "s": season}).fetchone()
    if row:
        conn.execute(text("UPDATE competitions SET name=:n,country=:c WHERE id=:id"), {"n": name, "c": country, "id": row[0]})
        return row[0]
    return conn.execute(text("INSERT INTO competitions(provider,provider_competition_id,name,country,season) VALUES(:p,:pid,:n,:c,:s)"),
                        {"p": provider, "pid": str(provider_comp_id), "n": name, "c": country, "s": season}).lastrowid


def sync_football_data_matches(matches):
    provider = "football-data.org"
    inserted = updated = 0
    now = _utc_now()
    with engine.begin() as conn:
        for item in matches:
            comp = item.get("competition") or {}
            season_obj = item.get("season") or {}
            season = str(season_obj.get("startDate", "")[:4] or "")
            comp_id = _upsert_competition(conn, provider, comp.get("id", comp.get("code", "unknown")),
                                          comp.get("name", "Unknown competition"),
                                          (comp.get("area") or {}).get("name"), season)
            home, away = item.get("homeTeam") or {}, item.get("awayTeam") or {}
            if not home.get("id") or not away.get("id"):
                continue
            home_id = _upsert_team(conn, provider, home["id"], home.get("name") or home.get("shortName") or f"Team {home['id']}")
            away_id = _upsert_team(conn, provider, away["id"], away.get("name") or away.get("shortName") or f"Team {away['id']}")
            match_id = str(item.get("id"))
            kickoff = item.get("utcDate")
            if not kickoff:
                continue
            score = item.get("score") or {}
            full = score.get("fullTime") or {}
            status = item.get("status", "SCHEDULED")
            hg, ag = full.get("home", None), full.get("away", None)
            existing = conn.execute(text("SELECT id FROM matches WHERE provider=:p AND provider_match_id=:mid"),
                                    {"p": provider, "mid": match_id}).fetchone()
            values = {"p": provider, "mid": match_id, "c": comp_id, "s": season, "ko": kickoff,
                      "h": home_id, "a": away_id, "st": status, "hg": hg, "ag": ag, "now": now}
            if existing:
                conn.execute(text("""UPDATE matches SET competition_id=:c,season=:s,kickoff_utc=:ko,
                    home_team_id=:h,away_team_id=:a,status=:st,home_goals=:hg,away_goals=:ag,source_updated_at=:now
                    WHERE id=:id"""), {**values, "id": existing[0]})
                updated += 1
            else:
                conn.execute(text("""INSERT INTO matches(provider,provider_match_id,competition_id,season,kickoff_utc,
                    home_team_id,away_team_id,status,home_goals,away_goals,source_updated_at)
                    VALUES(:p,:mid,:c,:s,:ko,:h,:a,:st,:hg,:ag,:now)"""), values)
                inserted += 1
        conn.execute(text("INSERT INTO data_sync_logs(provider,started_at,finished_at,status,records_received,records_inserted,records_updated) VALUES(:p,:n,:n,'SUCCESS',:r,:i,:u)"""),
                     {"p": provider, "n": now, "r": len(matches), "i": inserted, "u": updated})
    return {"received": len(matches), "inserted": inserted, "updated": updated}


def sync_api_football_fixtures(fixtures):
    provider = "api-football"
    inserted = updated = 0
    now = _utc_now()
    with engine.begin() as conn:
        for item in fixtures:
            fixture = item.get("fixture") or {}
            league = item.get("league") or {}
            teams = item.get("teams") or {}
            goals = item.get("goals") or {}
            home, away = teams.get("home") or {}, teams.get("away") or {}
            if not fixture.get("id") or not home.get("id") or not away.get("id") or not fixture.get("date"):
                continue
            season = str(league.get("season") or "")
            comp_id = _upsert_competition(conn, provider, league.get("id", "unknown"),
                                          league.get("name", "Unknown competition"),
                                          (league.get("country") or None), season)
            home_id = _upsert_team(conn, provider, home["id"], home.get("name", f"Team {home['id']}"))
            away_id = _upsert_team(conn, provider, away["id"], away.get("name", f"Team {away['id']}"))
            status_obj = fixture.get("status") or {}
            status_short = status_obj.get("short", "NS")
            status_map = {"NS": "SCHEDULED", "TBD": "SCHEDULED", "1H": "IN_PLAY", "HT": "IN_PLAY",
                          "2H": "IN_PLAY", "ET": "IN_PLAY", "P": "IN_PLAY", "FT": "FINISHED",
                          "AET": "FINISHED", "PEN": "FINISHED", "PST": "POSTPONED", "CANC": "CANCELLED",
                          "SUSP": "SUSPENDED", "ABD": "ABANDONED"}
            status = status_map.get(status_short, status_short)
            match_id = str(fixture["id"])
            existing = conn.execute(text("SELECT id FROM matches WHERE provider=:p AND provider_match_id=:mid"),
                                    {"p": provider, "mid": match_id}).fetchone()
            values = {"p": provider, "mid": match_id, "c": comp_id, "s": season, "ko": fixture["date"],
                      "h": home_id, "a": away_id, "st": status, "hg": goals.get("home"),
                      "ag": goals.get("away"), "neutral": int(bool(fixture.get("venue", {}).get("neutral"))) if isinstance(fixture.get("venue"), dict) else 0,
                      "now": now}
            if existing:
                conn.execute(text("""UPDATE matches SET competition_id=:c,season=:s,kickoff_utc=:ko,
                    home_team_id=:h,away_team_id=:a,status=:st,home_goals=:hg,away_goals=:ag,
                    neutral_venue=:neutral,source_updated_at=:now WHERE id=:id"""), {**values, "id": existing[0]})
                updated += 1
            else:
                conn.execute(text("""INSERT INTO matches(provider,provider_match_id,competition_id,season,kickoff_utc,
                    home_team_id,away_team_id,status,home_goals,away_goals,neutral_venue,source_updated_at)
                    VALUES(:p,:mid,:c,:s,:ko,:h,:a,:st,:hg,:ag,:neutral,:now)"""), values)
                inserted += 1
        conn.execute(text("INSERT INTO data_sync_logs(provider,started_at,finished_at,status,records_received,records_inserted,records_updated) VALUES(:p,:n,:n,'SUCCESS',:r,:i,:u)"""),
                     {"p": provider, "n": now, "r": len(fixtures), "i": inserted, "u": updated})
    return {"received": len(fixtures), "inserted": inserted, "updated": updated}


def log_sync_error(provider, message):
    now = _utc_now()
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO data_sync_logs(provider,started_at,finished_at,status,error_message) VALUES(:p,:n,:n,'FAILED',:e)"),
                     {"p": provider, "n": now, "e": str(message)[:1000]})


def set_team_alias(provider, provider_team_id, canonical_team_id, provider_name=None):
    """Map one provider team ID to a canonical team and re-point its existing fixtures."""
    with engine.begin() as conn:
        old = conn.execute(text("SELECT team_id FROM team_aliases WHERE provider=:p AND provider_team_id=:pid"),
                           {"p": provider, "pid": str(provider_team_id)}).fetchone()
        if not old:
            old = conn.execute(text("SELECT id FROM teams WHERE provider=:p AND provider_team_id=:pid"),
                               {"p": provider, "pid": str(provider_team_id)}).fetchone()
        if old:
            conn.execute(text("UPDATE matches SET home_team_id=:new WHERE provider=:p AND home_team_id=:old"),
                         {"new": canonical_team_id, "p": provider, "old": old[0]})
            conn.execute(text("UPDATE matches SET away_team_id=:new WHERE provider=:p AND away_team_id=:old"),
                         {"new": canonical_team_id, "p": provider, "old": old[0]})
        conn.execute(text("INSERT INTO team_aliases(team_id,provider,provider_team_id,provider_name) VALUES(:t,:p,:pid,:n) ON CONFLICT(provider,provider_team_id) DO UPDATE SET team_id=excluded.team_id, provider_name=excluded.provider_name"),
                     {"t": canonical_team_id, "p": provider, "pid": str(provider_team_id), "n": provider_name})
