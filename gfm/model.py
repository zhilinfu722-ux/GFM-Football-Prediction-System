"""GFM V1.2: time-decayed attack/defence + Elo + Poisson/Dixon-Coles.
Probabilities are estimates, not guarantees. Uses only matches before as_of.
"""
from __future__ import annotations
import math
import numpy as np
import pandas as pd
from scipy.stats import poisson

MODEL_VERSION = "GFM-1.2.0-elo-poisson-dc"


def _utc(value):
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _weighted_mean(values, weights, fallback):
    if len(values) == 0:
        return float(fallback)
    w = np.asarray(weights, dtype=float)
    if not np.isfinite(w).all() or w.sum() <= 0:
        return float(np.mean(values))
    return float(np.average(np.asarray(values, dtype=float), weights=w))


def _elo_ratings(history: pd.DataFrame, as_of, k_factor=20.0, home_advantage=55.0):
    ratings: dict[str, float] = {}
    if history.empty:
        return ratings
    h = history.copy()
    h["_date"] = pd.to_datetime(h["kickoff_utc"], utc=True, errors="coerce")
    h = h.dropna(subset=["_date", "home_goals", "away_goals"]).sort_values("_date")
    cutoff = _utc(as_of) if as_of is not None else (h["_date"].max() + pd.Timedelta(seconds=1))
    h = h[h["_date"] < cutoff]
    for row in h.itertuples(index=False):
        home, away = str(row.home_team), str(row.away_team)
        rh, ra = ratings.get(home, 1500.0), ratings.get(away, 1500.0)
        expected_home = 1.0 / (1.0 + 10.0 ** (-(rh + home_advantage - ra) / 400.0))
        if row.home_goals > row.away_goals:
            score_home = 1.0
        elif row.home_goals == row.away_goals:
            score_home = 0.5
        else:
            score_home = 0.0
        # Mild margin-of-victory multiplier; capped to avoid extreme score inflation.
        margin = min(1.5, math.log1p(abs(float(row.home_goals) - float(row.away_goals))))
        change = k_factor * max(0.5, margin) * (score_home - expected_home)
        ratings[home] = rh + change
        ratings[away] = ra - change
    return ratings


def _team_rates(history: pd.DataFrame, team: str, venue: str, as_of, half_life_days=180):
    h = history.copy()
    h["_date"] = pd.to_datetime(h["kickoff_utc"], utc=True, errors="coerce")
    h = h.dropna(subset=["_date", "home_goals", "away_goals"])
    cutoff = _utc(as_of) if as_of is not None else (h["_date"].max() + pd.Timedelta(seconds=1))
    h = h[(h["_date"] < cutoff) & ((h.home_team == team) | (h.away_team == team))]
    if venue == "home":
        h = h[h.home_team == team]
    elif venue == "away":
        h = h[h.away_team == team]
    if h.empty:
        return None
    age = (cutoff - h["_date"]).dt.total_seconds().clip(lower=0) / 86400.0
    weights = np.power(0.5, age / half_life_days)
    gf = np.where(h.home_team == team, h.home_goals, h.away_goals)
    ga = np.where(h.home_team == team, h.away_goals, h.home_goals)
    return _weighted_mean(gf, weights, 1.25), _weighted_mean(ga, weights, 1.25), len(h)


def predict_match(history: pd.DataFrame, home: str, away: str, as_of=None, neutral=False):
    required = {"kickoff_utc", "home_team", "away_team", "home_goals", "away_goals"}
    if history is None or history.empty:
        raise ValueError("没有已完成的历史比赛。请先导入历史赛果。")
    missing = required - set(history.columns)
    if missing:
        raise ValueError(f"历史数据缺少字段：{', '.join(sorted(missing))}")
    if home == away:
        raise ValueError("主队和客队不能是同一支球队。")
    h = history.copy()
    h["_date"] = pd.to_datetime(h["kickoff_utc"], utc=True, errors="coerce")
    h = h.dropna(subset=["_date", "home_goals", "away_goals"])
    h = h[(h.home_goals >= 0) & (h.away_goals >= 0)]
    cutoff = _utc(as_of) if as_of is not None else (h["_date"].max() + pd.Timedelta(seconds=1))
    h = h[h["_date"] < cutoff].drop(columns=["_date"])
    if h.empty:
        raise ValueError("指定比赛时间之前没有可用历史赛果。")

    league_home = max(float(h.home_goals.mean()), 0.15)
    league_away = max(float(h.away_goals.mean()), 0.15)
    hr = _team_rates(h, home, "home", cutoff)
    ar = _team_rates(h, away, "away", cutoff)
    # Venue-specific rates shrink toward league baselines with fewer observations.
    hgf, hga, hn = hr if hr else (league_home, league_away, 0)
    agf, aga, an = ar if ar else (league_away, league_home, 0)
    sh, sa = min(hn / 8.0, 1.0), min(an / 8.0, 1.0)
    home_attack = sh * (hgf / league_home) + (1 - sh)
    home_defence = sh * (hga / league_away) + (1 - sh)
    away_attack = sa * (agf / league_away) + (1 - sa)
    away_defence = sa * (aga / league_home) + (1 - sa)

    base_h = league_home * home_attack * away_defence
    base_a = league_away * away_attack * home_defence
    elo = _elo_ratings(h, cutoff)
    elo_diff = elo.get(home, 1500.0) - elo.get(away, 1500.0)
    # Elo provides a restrained strength adjustment around the goal-rate model.
    elo_factor = 1.12 ** (elo_diff / 400.0)
    lam_h = base_h * math.sqrt(elo_factor)
    lam_a = base_a / math.sqrt(elo_factor)
    if not neutral:
        lam_h *= 1.07
    lam_h = float(np.clip(lam_h, 0.10, 4.5))
    lam_a = float(np.clip(lam_a, 0.10, 4.5))

    max_goals = 10
    goals = np.arange(max_goals + 1)
    ph, pa = poisson.pmf(goals, lam_h), poisson.pmf(goals, lam_a)
    grid = np.outer(ph, pa)
    # Dixon-Coles low-score adjustment (rho fixed conservatively in baseline).
    rho = -0.06
    grid[0, 0] *= 1 - lam_h * lam_a * rho
    grid[0, 1] *= 1 + lam_h * rho
    grid[1, 0] *= 1 + lam_a * rho
    grid[1, 1] *= 1 - rho
    grid = np.clip(grid, 0, None)
    grid /= grid.sum()
    p_home = float(sum(grid[i, j] for i in range(max_goals + 1) for j in range(max_goals + 1) if i > j))
    p_draw = float(np.trace(grid))
    p_away = float(sum(grid[i, j] for i in range(max_goals + 1) for j in range(max_goals + 1) if i < j))
    idx = np.unravel_index(np.argmax(grid), grid.shape)
    btts = float((1 - math.exp(-lam_h)) * (1 - math.exp(-lam_a)))
    # Risk is non-win probability of the more likely outright winner.
    upset_risk = float(1 - max(p_home, p_away))
    n = min(hn, an)
    grade = "A" if n >= 15 else "B" if n >= 8 else "C" if n >= 4 else "D"
    return {
        "model_version": MODEL_VERSION, "p_home": p_home, "p_draw": p_draw, "p_away": p_away,
        "lambda_home": lam_h, "lambda_away": lam_a, "btts_yes": btts,
        "most_likely_score": f"{idx[0]}-{idx[1]}", "upset_risk": upset_risk,
        "confidence_grade": grade, "sample_min": n, "elo_home": elo.get(home, 1500.0),
        "elo_away": elo.get(away, 1500.0), "elo_diff": elo_diff,
    }
