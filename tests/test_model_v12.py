import pandas as pd
from gfm.model import predict_match, MODEL_VERSION
from gfm.backtest import walk_forward_backtest


def sample_history(n=60):
    rows=[]
    teams=["Alpha","Beta","Gamma","Delta"]
    for i in range(n):
        home=teams[i%4]; away=teams[(i+1)%4]
        rows.append({"kickoff_utc":f"2025-{(i//28)+1:02d}-{(i%28)+1:02d}T15:00:00Z",
                     "home_team":home,"away_team":away,"home_goals":1+(i%3==0),"away_goals":i%2})
    return pd.DataFrame(rows)


def test_v12_probability_and_model_version():
    hist=sample_history()
    pred=predict_match(hist,"Alpha","Beta","2026-01-01T00:00:00Z")
    assert pred["model_version"] == MODEL_VERSION
    assert abs(pred["p_home"]+pred["p_draw"]+pred["p_away"]-1) < 1e-8
    assert 0 <= pred["btts_yes"] <= 1


def test_walk_forward_backtest_metrics():
    hist=sample_history(60)
    metrics, rows=walk_forward_backtest(hist,min_history=30,max_matches=20)
    assert metrics["matches"] == len(rows)
    assert 0 <= metrics["accuracy"] <= 1
    assert metrics["brier_score"] >= 0
    assert metrics["log_loss"] >= 0
