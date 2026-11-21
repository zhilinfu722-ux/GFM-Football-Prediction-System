from sqlalchemy import create_engine, text
from gfm.db import SCHEMA
from gfm import sync


def make_engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test_gfm.db'}", future=True)
    with engine.begin() as conn:
        for statement in SCHEMA.strip().split(';'):
            if statement.strip():
                conn.execute(text(statement))
    return engine


def test_provider_sync_is_idempotent_and_aliasable(tmp_path, monkeypatch):
    engine = make_engine(tmp_path)
    monkeypatch.setattr(sync, "engine", engine)
    match = {
        "id": 771001,
        "utcDate": "2026-11-20T19:00:00Z",
        "status": "SCHEDULED",
        "competition": {"id": 2001, "name": "Test League", "area": {"name": "Testland"}},
        "season": {"startDate": "2026-08-01"},
        "homeTeam": {"id": 701, "name": "Test FC"},
        "awayTeam": {"id": 702, "name": "United Test"},
        "score": {"fullTime": {"home": None, "away": None}},
    }
    assert sync.sync_football_data_matches([match]) == {"received": 1, "inserted": 1, "updated": 0}
    assert sync.sync_football_data_matches([match]) == {"received": 1, "inserted": 0, "updated": 1}

    with engine.connect() as conn:
        canonical_id = conn.execute(text("SELECT id FROM teams WHERE name='United Test'")).scalar_one()
    sync.set_team_alias("football-data.org", "701", canonical_id, "Test FC")
    sync.sync_football_data_matches([match])
    with engine.connect() as conn:
        home_id = conn.execute(text("SELECT home_team_id FROM matches WHERE provider_match_id='771001'")).scalar_one()
    assert home_id == canonical_id
    engine.dispose()
