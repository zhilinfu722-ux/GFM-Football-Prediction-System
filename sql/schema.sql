-- GFM V1.1 schema. Runtime initialization/migration is handled by gfm/db.py.
CREATE TABLE IF NOT EXISTS competitions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, provider TEXT, provider_competition_id TEXT,
 name TEXT NOT NULL, country TEXT, season TEXT,
 UNIQUE(provider, provider_competition_id, season)
);
CREATE TABLE IF NOT EXISTS teams (
 id INTEGER PRIMARY KEY AUTOINCREMENT, provider TEXT, provider_team_id TEXT,
 name TEXT NOT NULL, country TEXT, UNIQUE(provider, provider_team_id)
);
CREATE TABLE IF NOT EXISTS matches (
 id INTEGER PRIMARY KEY AUTOINCREMENT, provider TEXT, provider_match_id TEXT,
 competition_id INTEGER, season TEXT, kickoff_utc TEXT NOT NULL,
 home_team_id INTEGER NOT NULL, away_team_id INTEGER NOT NULL,
 status TEXT DEFAULT 'SCHEDULED', home_goals INTEGER, away_goals INTEGER,
 neutral_venue INTEGER DEFAULT 0, source_updated_at TEXT,
 UNIQUE(provider, provider_match_id),
 FOREIGN KEY(competition_id) REFERENCES competitions(id),
 FOREIGN KEY(home_team_id) REFERENCES teams(id), FOREIGN KEY(away_team_id) REFERENCES teams(id)
);
CREATE TABLE IF NOT EXISTS team_aliases (
 id INTEGER PRIMARY KEY AUTOINCREMENT, team_id INTEGER NOT NULL, provider TEXT NOT NULL,
 provider_team_id TEXT NOT NULL, provider_name TEXT,
 UNIQUE(provider, provider_team_id), FOREIGN KEY(team_id) REFERENCES teams(id)
);
CREATE TABLE IF NOT EXISTS data_sync_logs (
 id INTEGER PRIMARY KEY AUTOINCREMENT, provider TEXT NOT NULL, started_at TEXT NOT NULL,
 finished_at TEXT, status TEXT NOT NULL, records_received INTEGER DEFAULT 0,
 records_inserted INTEGER DEFAULT 0, records_updated INTEGER DEFAULT 0, error_message TEXT
);
