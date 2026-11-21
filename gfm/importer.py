import pandas as pd
from sqlalchemy import text
from .db import engine


FOOTBALL_DATA_COLUMNS = {"Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"}
GFM_COLUMNS = {
    "kickoff_utc", "home_team", "away_team",
    "home_goals", "away_goals",
}


def _clean_text(value, default=""):
    if pd.isna(value):
        return default
    value = str(value).strip()
    return value if value else default


def _parse_dates(values, dayfirst=False):
    # Keep invalid dates as NaT so they can be excluded before string conversion.
    return pd.to_datetime(values, dayfirst=dayfirst, errors="coerce", utc=True)


def _prepare_rows(df, competition, season, provider):
    columns = set(df.columns)

    if FOOTBALL_DATA_COLUMNS.issubset(columns):
        out = pd.DataFrame(index=df.index)
        out["kickoff"] = _parse_dates(df["Date"], dayfirst=True)
        out["home_team"] = df["HomeTeam"].map(lambda x: _clean_text(x))
        out["away_team"] = df["AwayTeam"].map(lambda x: _clean_text(x))
        out["home_goals"] = pd.to_numeric(df["FTHG"], errors="coerce")
        out["away_goals"] = pd.to_numeric(df["FTAG"], errors="coerce")
        out["competition"] = competition
        out["season"] = season
        out["provider"] = provider
        out["provider_match_id"] = ""
    elif GFM_COLUMNS.issubset(columns):
        out = pd.DataFrame(index=df.index)
        out["kickoff"] = _parse_dates(df["kickoff_utc"], dayfirst=False)
        out["home_team"] = df["home_team"].map(lambda x: _clean_text(x))
        out["away_team"] = df["away_team"].map(lambda x: _clean_text(x))
        out["home_goals"] = pd.to_numeric(df["home_goals"], errors="coerce")
        out["away_goals"] = pd.to_numeric(df["away_goals"], errors="coerce")
        out["competition"] = df["competition"].map(
            lambda x: _clean_text(x, competition)
        ) if "competition" in columns else competition
        out["season"] = df["season"].map(
            lambda x: _clean_text(x, season)
        ) if "season" in columns else season
        out["provider"] = df["provider"].map(
            lambda x: _clean_text(x, provider)
        ) if "provider" in columns else provider
        out["provider_match_id"] = df["provider_match_id"].map(
            lambda x: _clean_text(x)
        ) if "provider_match_id" in columns else ""
        if "status" in columns:
            status = df["status"].map(lambda x: _clean_text(x).upper())
            # A history import must contain a completed result, not a scheduled match.
            out = out.loc[status.isin(
                {"FINISHED", "FT", "COMPLETED", "AET", "PEN"}
            )].copy()
    else:
        if FOOTBALL_DATA_COLUMNS.issubset(columns) is False and GFM_COLUMNS.issubset(columns) is False:
            raise ValueError(
                "不支持的 CSV 格式。请使用 Football-Data 格式 "
                "(Date, HomeTeam, AwayTeam, FTHG, FTAG)，或 GFM 原生格式 "
                "(kickoff_utc, home_team, away_team, home_goals, away_goals)。"
            )

    # Scores must be present, non-negative integers. Invalid rows are skipped.
    valid = (
        out["kickoff"].notna()
        & out["home_team"].ne("")
        & out["away_team"].ne("")
        & out["home_goals"].notna()
        & out["away_goals"].notna()
        & (out["home_goals"] >= 0)
        & (out["away_goals"] >= 0)
        & (out["home_goals"] % 1 == 0)
        & (out["away_goals"] % 1 == 0)
    )
    return out.loc[valid].copy()


def import_football_data_csv(
    file_or_path,
    competition="Imported League",
    season="unknown",
    provider="csv_import",
):
    """
    Import either Football-Data CSV or GFM's own exported match CSV.
    Returns the number of newly inserted finished matches.
    """
    df = pd.read_csv(file_or_path, encoding="utf-8-sig")

    # An empty template with headers is valid input and inserts zero rows.
    if df.empty:
        cols = set(df.columns)
        if not (
            FOOTBALL_DATA_COLUMNS.issubset(cols)
            or GFM_COLUMNS.issubset(cols)
        ):
            raise ValueError("CSV 没有数据行，且表头不属于支持的格式。")
        return 0

    rows = _prepare_rows(df, competition, season, provider)
    inserted = 0

    with engine.begin() as conn:
        competition_ids = {}

        for _, row in rows.iterrows():
            comp_name = _clean_text(row["competition"], competition)
            season_name = _clean_text(row["season"], season)
            row_provider = _clean_text(row["provider"], provider)
            comp_key = (comp_name, season_name, row_provider)

            if comp_key not in competition_ids:
                comp = conn.execute(
                    text(
                        "SELECT id FROM competitions "
                        "WHERE name=:n AND season=:s LIMIT 1"
                    ),
                    {"n": comp_name, "s": season_name},
                ).fetchone()
                if comp:
                    comp_id = comp[0]
                else:
                    result = conn.execute(
                        text(
                            "INSERT INTO competitions(name,season,provider) "
                            "VALUES(:n,:s,:p)"
                        ),
                        {"n": comp_name, "s": season_name, "p": row_provider},
                    )
                    comp_id = result.lastrowid
                competition_ids[comp_key] = comp_id

            home_name = _clean_text(row["home_team"])
            away_name = _clean_text(row["away_team"])
            team_ids = []

            for team_name in (home_name, away_name):
                team = conn.execute(
                    text("SELECT id FROM teams WHERE name=:n LIMIT 1"),
                    {"n": team_name},
                ).fetchone()
                if team:
                    team_ids.append(team[0])
                else:
                    result = conn.execute(
                        text("INSERT INTO teams(name,provider) VALUES(:n,:p)"),
                        {"n": team_name, "p": row_provider},
                    )
                    team_ids.append(result.lastrowid)

            kickoff_utc = row["kickoff"].isoformat()
            supplied_id = _clean_text(row["provider_match_id"])
            match_key = supplied_id or (
                f"{comp_name}|{season_name}|{kickoff_utc}|"
                f"{home_name}|{away_name}"
            )

            exists = conn.execute(
                text(
                    "SELECT id FROM matches "
                    "WHERE provider=:p AND provider_match_id=:k"
                ),
                {"p": row_provider, "k": match_key},
            ).fetchone()
            if exists:
                continue

            conn.execute(
                text(
                    """INSERT INTO matches(
                        provider, provider_match_id, competition_id, season,
                        kickoff_utc, home_team_id, away_team_id, status,
                        home_goals, away_goals
                    ) VALUES(
                        :p, :k, :c, :s, :d, :h, :a, 'FINISHED', :hg, :ag
                    )"""
                ),
                {
                    "p": row_provider,
                    "k": match_key,
                    "c": competition_ids[comp_key],
                    "s": season_name,
                    "d": kickoff_utc,
                    "h": team_ids[0],
                    "a": team_ids[1],
                    "hg": int(row["home_goals"]),
                    "ag": int(row["away_goals"]),
                },
            )
            inserted += 1

    return inserted
