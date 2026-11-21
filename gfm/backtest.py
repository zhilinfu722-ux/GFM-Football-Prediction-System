"""Chronological walk-forward evaluation; every prediction sees prior matches only."""
import math
import pandas as pd
from .model import predict_match


def walk_forward_backtest(matches: pd.DataFrame, min_history: int = 30, max_matches: int = 500):
    required = {"kickoff_utc", "home_team", "away_team", "home_goals", "away_goals"}
    if matches is None or matches.empty:
        raise ValueError("没有可回测的历史比赛数据。")
    missing = required - set(matches.columns)
    if missing:
        raise ValueError(f"回测数据缺少字段：{', '.join(sorted(missing))}")
    df = matches.copy()
    df["_date"] = pd.to_datetime(df.kickoff_utc, utc=True, errors="coerce")
    df = df.dropna(subset=["_date", "home_goals", "away_goals"]).sort_values("_date").reset_index(drop=True)
    if len(df) <= min_history:
        raise ValueError(f"有效比赛只有 {len(df)} 场，至少需要超过 {min_history} 场。")
    # Cap runtime by evenly sampling the latest section while preserving chronology.
    start = min_history
    eval_indices = list(range(start, len(df)))
    if len(eval_indices) > max_matches:
        step = max(1, len(eval_indices) // max_matches)
        eval_indices = eval_indices[::step][-max_matches:]
    rows = []
    for idx in eval_indices:
        row = df.iloc[idx]
        prior = df.iloc[:idx].drop(columns=["_date"])
        try:
            pred = predict_match(prior, str(row.home_team), str(row.away_team), row.kickoff_utc)
        except Exception:
            continue
        actual = 0 if row.home_goals > row.away_goals else 1 if row.home_goals == row.away_goals else 2
        probs = [pred["p_home"], pred["p_draw"], pred["p_away"]]
        chosen = int(max(range(3), key=lambda i: probs[i]))
        onehot = [1.0 if i == actual else 0.0 for i in range(3)]
        brier = sum((probs[i] - onehot[i]) ** 2 for i in range(3)) / 3.0
        logloss = -math.log(max(probs[actual], 1e-12))
        rows.append({"date": row.kickoff_utc, "home": row.home_team, "away": row.away_team,
                     "actual": ["主胜", "平局", "客胜"][actual],
                     "predicted": ["主胜", "平局", "客胜"][chosen],
                     "p_home": probs[0], "p_draw": probs[1], "p_away": probs[2],
                     "correct": int(chosen == actual), "brier": brier, "log_loss": logloss})
    if not rows:
        raise ValueError("没有生成有效回测样本，请检查球队名称和比赛日期。")
    result = pd.DataFrame(rows)
    metrics = {"matches": len(result), "accuracy": float(result.correct.mean()),
               "brier_score": float(result.brier.mean()), "log_loss": float(result.log_loss.mean())}
    return metrics, result
