# Changelog

## V1.1 — Data ingestion and match management

- Added optional football-data.org v4 fixture/competition adapter.
- Added optional API-Football v3 fixture adapter.
- Added provider match ID deduplication and repeat-sync updates.
- Added team alias mapping and existing-fixture team ID reconciliation.
- Added match manager with date/status filters and CSV export.
- Added data synchronization logs and failure records.
- Added environment-based API key configuration.
- Kept the V1.0 baseline prediction engine unchanged; no accuracy claim is implied.

## V1.2 — Local Windows package and prediction engine upgrade

- Added Windows one-click launcher (`START_GFM.bat`) and database backup script (`BACKUP_GFM.bat`).
- Reworked dashboard into overview, match management, CSV import, provider sync, prediction, result entry, walk-forward backtest, and prediction history/backup sections.
- Upgraded baseline model to time-decayed venue-specific attack/defence + Elo + Poisson score grid + fixed-parameter Dixon-Coles low-score adjustment.
- Added chronological walk-forward backtest with accuracy, multiclass Brier score, and log loss.
- Added manual fixture creation and actual result entry.
- Added model version and input snapshot to saved predictions.
- Added V1.2 model and backtest tests.
- Limitations: no live provider account verification, no league-specific parameter fitting, no probability calibration, no xG/injury/lineup feed, and no claim of predictive profitability.
