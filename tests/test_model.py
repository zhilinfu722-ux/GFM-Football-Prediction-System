import pandas as pd
from gfm.model import predict_match

def test_probabilities_sum_to_one():
    rows=[]
    for i in range(20):
        rows.append({"kickoff_utc":f"2025-01-{(i%28)+1:02d}T12:00:00Z","home_team":"A","away_team":"B","home_goals":2 if i%2 else 1,"away_goals":1 if i%2 else 0})
        rows.append({"kickoff_utc":f"2025-02-{(i%28)+1:02d}T12:00:00Z","home_team":"B","away_team":"A","home_goals":1,"away_goals":1 if i%2 else 2})
    result=predict_match(pd.DataFrame(rows),"A","B")
    assert abs(result["p_home"]+result["p_draw"]+result["p_away"]-1)<1e-8
    assert 0 <= result["btts_yes"] <= 1
