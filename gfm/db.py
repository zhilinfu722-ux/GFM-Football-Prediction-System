from sqlalchemy import create_engine, text
from pathlib import Path
import os

DB_URL = os.getenv("DATABASE_URL", "sqlite:///./data/gfm.db")
if DB_URL.startswith("sqlite:///./"):
    Path("data").mkdir(exist_ok=True)
engine = create_engine(DB_URL, future=True)

SCHEMA = """
CREATE TABLE IF NOT EXISTS competitions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, provider TEXT, provider_competition_id TEXT,
 name TEXT NOT NULL, country TEXT, season TEXT, UNIQUE(provider, provider_competition_id, season)
);
CREATE TABLE IF NOT EXISTS teams (
 id INTEGER PRIMARY KEY AUTOINCREMENT, provider TEXT, provider_team_id TEXT,
 name TEXT NOT NULL, country TEXT, UNIQUE(provider, provider_team_id)
);
CREATE TABLE IF NOT EXISTS matches (
 id INTEGER PRIMARY KEY AUTOINCREMENT, provider TEXT, provider_match_id TEXT,
 competition_id INTEGER, season TEXT, kickoff_utc TEXT NOT NULL, home_team_id INTEGER NOT NULL,
 away_team_id INTEGER NOT NULL, status TEXT DEFAULT 'SCHEDULED', home_goals INTEGER,
 away_goals INTEGER, neutral_venue INTEGER DEFAULT 0, source_updated_at TEXT,
 UNIQUE(provider, provider_match_id),
 FOREIGN KEY(competition_id) REFERENCES competitions(id),
 FOREIGN KEY(home_team_id) REFERENCES teams(id), FOREIGN KEY(away_team_id) REFERENCES teams(id)
);
CREATE TABLE IF NOT EXISTS team_match_stats (
 id INTEGER PRIMARY KEY AUTOINCREMENT, match_id INTEGER NOT NULL, team_id INTEGER NOT NULL,
 is_home INTEGER NOT NULL, xg REAL, shots REAL, shots_on_target REAL, source TEXT,
 FOREIGN KEY(match_id) REFERENCES matches(id), FOREIGN KEY(team_id) REFERENCES teams(id)
);
CREATE TABLE IF NOT EXISTS predictions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, match_id INTEGER NOT NULL, model_version TEXT NOT NULL,
 created_at TEXT NOT NULL, p_home REAL NOT NULL, p_draw REAL NOT NULL, p_away REAL NOT NULL,
 lambda_home REAL, lambda_away REAL, btts_yes REAL, most_likely_score TEXT,
 upset_risk REAL, confidence_grade TEXT, input_snapshot TEXT,
 FOREIGN KEY(match_id) REFERENCES matches(id)
);
CREATE TABLE IF NOT EXISTS results (
 id INTEGER PRIMARY KEY AUTOINCREMENT, match_id INTEGER NOT NULL UNIQUE,
 home_goals INTEGER NOT NULL, away_goals INTEGER NOT NULL, verified_at TEXT,
 source TEXT, FOREIGN KEY(match_id) REFERENCES matches(id)
);
CREATE TABLE IF NOT EXISTS model_runs (
 id INTEGER PRIMARY KEY AUTOINCREMENT, model_version TEXT NOT NULL, run_at TEXT NOT NULL,
 train_start TEXT, train_end TEXT, metrics_json TEXT, notes TEXT
);
CREATE TABLE IF NOT EXISTS data_sources (
 id INTEGER PRIMARY KEY AUTOINCREMENT, source_name TEXT NOT NULL, source_type TEXT,
 terms_url TEXT, permitted_use TEXT, last_sync_at TEXT, status TEXT, notes TEXT
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
"""

def init_db():
    with engine.begin() as conn:
        for stmt in SCHEMA.strip().split(';'):
            if stmt.strip(): conn.execute(text(stmt))

def query_df(sql, params=None):
    import pandas as pd
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn, params=params or {})
