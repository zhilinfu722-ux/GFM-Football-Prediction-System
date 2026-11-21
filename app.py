from __future__ import annotations
import os, json, shutil
from pathlib import Path
from datetime import date, datetime, timedelta, timezone, time
import streamlit as st
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import text

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
load_dotenv(ROOT / ".env")
from gfm.db import init_db, engine, query_df
from gfm.importer import import_football_data_csv
from gfm.model import predict_match, MODEL_VERSION
from gfm.backtest import walk_forward_backtest
from gfm.sources import football_data_org, api_football
from gfm.sync import sync_football_data_matches, sync_api_football_fixtures, log_sync_error

st.set_page_config(page_title="GFM 足球预测系统", page_icon="⚽", layout="wide")
init_db()

st.title("⚽ GFM 足球预测系统")
st.caption(f"本地运行 · 免费数据优先 · 当前模型 {MODEL_VERSION} · 预测概率可追溯")


def get_history():
    return query_df("""SELECT m.kickoff_utc, ht.name home_team, at.name away_team,
        m.home_goals, m.away_goals FROM matches m
        JOIN teams ht ON ht.id=m.home_team_id JOIN teams at ON at.id=m.away_team_id
        WHERE m.status='FINISHED' AND m.home_goals IS NOT NULL AND m.away_goals IS NOT NULL
        ORDER BY m.kickoff_utc""")


def log_error(provider, exc):
    try:
        log_sync_error(provider, str(exc))
    except Exception:
        pass
    st.error(str(exc))


tabs = st.tabs(["总览", "赛事管理", "历史数据导入", "数据源同步", "比赛预测", "赛果录入", "历史回测", "预测记录与备份"])

with tabs[0]:
    st.subheader("系统总览")
    stats = query_df("""SELECT
        (SELECT COUNT(*) FROM competitions) competitions,
        (SELECT COUNT(*) FROM teams) teams,
        (SELECT COUNT(*) FROM matches) matches,
        (SELECT COUNT(*) FROM matches WHERE status='FINISHED') finished,
        (SELECT COUNT(*) FROM predictions) predictions""").iloc[0]
    cols = st.columns(5)
    for col, label, key in zip(cols, ["赛事/联赛", "球队", "比赛总数", "已完赛", "预测记录"], stats.index):
        col.metric(label, int(stats[key]))
    st.markdown("#### 最近比赛")
    recent = query_df("""SELECT m.kickoff_utc, c.name competition, h.name home_team, a.name away_team,
        m.status, m.home_goals, m.away_goals, m.provider
        FROM matches m LEFT JOIN competitions c ON c.id=m.competition_id
        JOIN teams h ON h.id=m.home_team_id JOIN teams a ON a.id=m.away_team_id
        ORDER BY m.kickoff_utc DESC LIMIT 12""")
    st.dataframe(recent, use_container_width=True, hide_index=True)
    st.info("首次使用：先在「历史数据导入」导入历史赛果，再在「比赛预测」选择或创建比赛。没有 API 密钥时，CSV 模式仍可正常使用。")

with tabs[1]:
    st.subheader("赛事管理")
    teams_df = query_df("SELECT id,name FROM teams ORDER BY name")
    with st.expander("手动新增比赛", expanded=teams_df.empty):
        if len(teams_df) < 2:
            st.warning("至少需要两支球队。请先导入历史数据或同步赛事。")
        else:
            names = teams_df.name.tolist()
            c1,c2,c3 = st.columns(3)
            home = c1.selectbox("主队", names, key="new_home")
            away = c2.selectbox("客队", [x for x in names if x != home], key="new_away")
            match_date = c3.date_input("比赛日期", value=date.today()+timedelta(days=1), key="new_date")
            c4,c5 = st.columns(2)
            match_time = c4.time_input("开球时间（本地时间）", value=time(20,0), key="new_time")
            neutral = c5.checkbox("中立场", key="new_neutral")
            competition_name = st.text_input("赛事名称", value="手动录入", key="new_comp")
            if st.button("创建比赛", type="primary"):
                if home == away:
                    st.error("主客队不能相同。")
                else:
                    ko = datetime.combine(match_date, match_time).astimezone().astimezone(timezone.utc).isoformat()
                    ids = dict(zip(teams_df.name, teams_df.id))
                    key = f"{ko}|{ids[home]}|{ids[away]}"
                    with engine.begin() as conn:
                        comp = conn.execute(text("SELECT id FROM competitions WHERE name=:n AND provider='manual' LIMIT 1"), {"n":competition_name}).fetchone()
                        cid = comp[0] if comp else conn.execute(text("INSERT INTO competitions(name,provider) VALUES(:n,'manual')"), {"n":competition_name}).lastrowid
                        conn.execute(text("INSERT OR IGNORE INTO matches(provider,provider_match_id,competition_id,kickoff_utc,home_team_id,away_team_id,status,neutral_venue) VALUES('manual',:k,:c,:ko,:h,:a,'SCHEDULED',:n)"), {"k":key,"c":cid,"ko":ko,"h":ids[home],"a":ids[away],"n":int(neutral)})
                    st.success("比赛已创建。")
    c1,c2,c3 = st.columns(3)
    status = c1.selectbox("比赛状态", ["全部","SCHEDULED","IN_PLAY","FINISHED","POSTPONED","CANCELLED"])
    start = c2.date_input("开始日期", date.today()-timedelta(days=30), key="mgr_start")
    end = c3.date_input("结束日期", date.today()+timedelta(days=30), key="mgr_end")
    sql = """SELECT m.id, c.name competition, m.season, m.kickoff_utc, h.name home_team, a.name away_team,
        m.status, m.home_goals, m.away_goals, m.provider, m.provider_match_id
        FROM matches m LEFT JOIN competitions c ON c.id=m.competition_id
        JOIN teams h ON h.id=m.home_team_id JOIN teams a ON a.id=m.away_team_id
        WHERE date(m.kickoff_utc) BETWEEN :s AND :e"""
    params={"s":start.isoformat(),"e":end.isoformat()}
    if status != "全部": sql += " AND m.status=:status"; params["status"]=status
    data = query_df(sql+" ORDER BY m.kickoff_utc",params)
    st.metric("符合条件的比赛",len(data))
    st.dataframe(data,use_container_width=True,hide_index=True)
    st.download_button("导出比赛 CSV",data.to_csv(index=False).encode("utf-8-sig"),"gfm_matches.csv","text/csv")

with tabs[2]:
    st.subheader("历史数据导入")
    st.write("支持 Football-Data 格式：Date、HomeTeam、AwayTeam、FTHG、FTAG。日期按 UTC 解释；若原始数据为其他时区，请先转换。")
    uploaded=st.file_uploader("选择历史比赛 CSV",type=["csv"],key="history_csv")
    c1,c2=st.columns(2)
    comp=c1.text_input("联赛名称", "Imported League")
    season=c2.text_input("赛季", "2025/26")
    if uploaded and st.button("导入历史赛果",type="primary"):
        try:
            count=import_football_data_csv(uploaded,comp,season)
            st.success(f"导入完成，新增 {count} 场比赛。重复记录会跳过。")
        except Exception as exc: st.error(f"导入失败：{exc}")
    st.markdown("**CSV 示例**")
    st.code("Date,HomeTeam,AwayTeam,FTHG,FTAG\n01/08/2025,Team A,Team B,2,1\n02/08/2025,Team C,Team D,0,0",language="csv")
    st.download_button("下载 CSV 模板",b"Date,HomeTeam,AwayTeam,FTHG,FTAG\n01/08/2025,Team A,Team B,2,1\n","gfm_csv_template.csv","text/csv")

with tabs[3]:
    st.subheader("数据源同步")
    st.warning("API 密钥仅保存在本机 .env 文件。请先确认免费套餐对目标赛事和赛季的覆盖。")
    provider=st.radio("数据源",["football-data.org","API-Football"],horizontal=True)
    c1,c2=st.columns(2)
    d1=c1.date_input("开始日期",date.today(),key="api_from")
    d2=c2.date_input("结束日期",date.today()+timedelta(days=7),key="api_to")
    if d1>d2: st.error("日期范围无效。")
    elif provider=="football-data.org":
        code=st.text_input("赛事代码", "PL", help="例如 PL、PD、BL1；实际可用范围由账号套餐决定。")
        if st.button("同步 football-data.org"):
            try:
                token=os.getenv("FOOTBALL_DATA_TOKEN","")
                rows=football_data_org.fetch_matches(token,code,d1,d2)
                result=sync_football_data_matches(rows)
                st.success(f"同步完成：收到 {result['received']}，新增 {result['inserted']}，更新 {result['updated']}。")
            except Exception as exc: log_error("football-data.org",exc)
    else:
        league=st.text_input("联赛 ID（可选）","")
        season_value=st.text_input("赛季年份（可选，例如 2025）","")
        if st.button("同步 API-Football"):
            try:
                rows,paging=api_football.fetch_fixtures(os.getenv("API_FOOTBALL_KEY",""),d1.isoformat(),d2.isoformat(),league or None,season_value or None)
                result=sync_api_football_fixtures(rows)
                st.success(f"同步完成：收到 {result['received']}，新增 {result['inserted']}，更新 {result['updated']}。分页：{paging}")
            except Exception as exc: log_error("api-football",exc)
    st.caption("当前是手动触发同步，不会后台持续轮询。避免消耗免费 API 配额。")

with tabs[4]:
    st.subheader("比赛预测")
    fixtures=query_df("""SELECT m.id,m.kickoff_utc,h.name home,a.name away,m.neutral_venue,m.status
        FROM matches m JOIN teams h ON h.id=m.home_team_id JOIN teams a ON a.id=m.away_team_id
        WHERE m.status IN ('SCHEDULED','TIMED','IN_PLAY') ORDER BY m.kickoff_utc DESC LIMIT 500""")
    if fixtures.empty:
        st.info("目前没有待预测比赛。请先导入数据、同步赛程或手动新增比赛。")
    else:
        labels={f"#{r.id} · {r.kickoff_utc} · {r.home} vs {r.away} · {r.status}":r for r in fixtures.itertuples(index=False)}
        selected=st.selectbox("选择比赛",list(labels.keys()))
        match=labels[selected]
        st.write(f"**{match.home} vs {match.away}** · 开球时间：{match.kickoff_utc}")
        history=get_history()
        if st.button("运行 GFM 预测",type="primary"):
            try:
                result=predict_match(history,match.home,match.away,match.kickoff_utc,bool(match.neutral_venue))
                st.session_state["gfm_current_prediction"]={"match_id":int(match.id),"result":result}
            except Exception as exc: st.error(str(exc))
        saved=st.session_state.get("gfm_current_prediction")
        if saved and saved["match_id"]==int(match.id):
            r=saved["result"]
            a,b,c=st.columns(3)
            a.metric("主胜",f"{r['p_home']:.1%}"); b.metric("平局",f"{r['p_draw']:.1%}"); c.metric("客胜",f"{r['p_away']:.1%}")
            a,b,c=st.columns(3)
            a.metric("预期进球",f"{r['lambda_home']:.2f} : {r['lambda_away']:.2f}")
            b.metric("双方进球",f"{r['btts_yes']:.1%}")
            c.metric("最可能比分",r["most_likely_score"])
            st.write(f"热门方不胜风险：**{r['upset_risk']:.1%}** · 样本充分度：**{r['confidence_grade']}** · Elo：{r['elo_home']:.0f} vs {r['elo_away']:.0f}")
            st.caption("样本充分度不是命中概率。当前模型尚需针对具体联赛完成正式回测与概率校准。")
            if st.button("保存这次预测"):
                snap={"model":r["model_version"],"history_matches":len(history),"home_elo":r["elo_home"],"away_elo":r["elo_away"],"note":"Prediction frozen at creation time"}
                with engine.begin() as conn:
                    conn.execute(text("""INSERT INTO predictions(match_id,model_version,created_at,p_home,p_draw,p_away,lambda_home,lambda_away,btts_yes,most_likely_score,upset_risk,confidence_grade,input_snapshot)
                        VALUES(:mid,:v,:t,:ph,:pd,:pa,:lh,:la,:bt,:sc,:ur,:cg,:snap)"""),
                        {"mid":int(match.id),"v":r["model_version"],"t":datetime.now(timezone.utc).isoformat(),"ph":r["p_home"],"pd":r["p_draw"],"pa":r["p_away"],"lh":r["lambda_home"],"la":r["lambda_away"],"bt":r["btts_yes"],"sc":r["most_likely_score"],"ur":r["upset_risk"],"cg":r["confidence_grade"],"snap":json.dumps(snap,ensure_ascii=False)})
                st.success("预测已保存，历史记录不会被后续模型覆盖。")

with tabs[5]:
    st.subheader("赛果录入")
    pending=query_df("""SELECT m.id,m.kickoff_utc,h.name home,a.name away,m.status
        FROM matches m JOIN teams h ON h.id=m.home_team_id JOIN teams a ON a.id=m.away_team_id
        WHERE m.status!='FINISHED' ORDER BY m.kickoff_utc DESC LIMIT 500""")
    if pending.empty: st.info("没有待录入赛果的比赛。")
    else:
        opts={f"#{r.id} · {r.home} vs {r.away} · {r.kickoff_utc}":r for r in pending.itertuples(index=False)}
        chosen=st.selectbox("选择比赛",list(opts.keys()),key="result_match")
        row=opts[chosen]
        c1,c2,c3=st.columns(3)
        hg=c1.number_input("主队进球",min_value=0,max_value=30,value=0,key="result_h")
        ag=c2.number_input("客队进球",min_value=0,max_value=30,value=0,key="result_a")
        source=c3.text_input("赛果来源",value="manual")
        if st.button("保存实际赛果"):
            now=datetime.now(timezone.utc).isoformat()
            with engine.begin() as conn:
                conn.execute(text("UPDATE matches SET status='FINISHED',home_goals=:h,away_goals=:a,source_updated_at=:t WHERE id=:id"),{"h":int(hg),"a":int(ag),"t":now,"id":int(row.id)})
                conn.execute(text("INSERT INTO results(match_id,home_goals,away_goals,verified_at,source) VALUES(:id,:h,:a,:t,:s) ON CONFLICT(match_id) DO UPDATE SET home_goals=excluded.home_goals,away_goals=excluded.away_goals,verified_at=excluded.verified_at,source=excluded.source"),{"id":int(row.id),"h":int(hg),"a":int(ag),"t":now,"s":source})
            st.success("赛果已保存。")

with tabs[6]:
    st.subheader("历史回测")
    hist=get_history()
    st.write(f"当前可用已完赛样本：**{len(hist)} 场**")
    min_history=st.number_input("每次预测至少使用此前多少场比赛",min_value=10,max_value=500,value=30,step=10)
    max_eval=st.number_input("最多评估比赛数量",min_value=20,max_value=1000,value=200,step=20)
    if st.button("运行时间顺序回测",type="primary"):
        try:
            metrics,detail=walk_forward_backtest(hist,int(min_history),int(max_eval))
            st.session_state["gfm_backtest"]={"metrics":metrics,"detail":detail}
        except Exception as exc: st.error(str(exc))
    bt=st.session_state.get("gfm_backtest")
    if bt:
        m=bt["metrics"]
        a,b,c,d=st.columns(4)
        a.metric("评估场次",m["matches"]); b.metric("胜平负命中率",f"{m['accuracy']:.1%}")
        c.metric("Brier Score",f"{m['brier_score']:.4f}"); d.metric("Log Loss",f"{m['log_loss']:.4f}")
        st.dataframe(bt["detail"],use_container_width=True,hide_index=True)
        st.download_button("下载回测明细 CSV",bt["detail"].to_csv(index=False).encode("utf-8-sig"),"gfm_backtest.csv","text/csv")
        st.caption("这是按时间顺序的简单 walk-forward 回测；尚未按联赛分层、校准概率或与市场基准比较。")

with tabs[7]:
    st.subheader("预测记录")
    records=query_df("""SELECT p.id,p.created_at,c.name competition,h.name home,a.name away,
        p.p_home,p.p_draw,p.p_away,p.most_likely_score,p.upset_risk,p.confidence_grade,p.model_version
        FROM predictions p JOIN matches m ON m.id=p.match_id LEFT JOIN competitions c ON c.id=m.competition_id
        JOIN teams h ON h.id=m.home_team_id JOIN teams a ON a.id=m.away_team_id ORDER BY p.created_at DESC LIMIT 1000""")
    st.dataframe(records,use_container_width=True,hide_index=True)
    st.download_button("导出预测记录 CSV",records.to_csv(index=False).encode("utf-8-sig"),"gfm_predictions.csv","text/csv")
    st.divider(); st.subheader("数据库备份")
    db_path=ROOT/"data"/"gfm.db"
    if db_path.exists():
        st.write(f"数据库文件：`{db_path}` · {db_path.stat().st_size/1024:.1f} KB")
        with open(db_path,"rb") as f:
            st.download_button("下载数据库备份",f.read(),f"gfm_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db","application/octet-stream")
    logs=query_df("SELECT id,provider,started_at,status,records_received,records_inserted,records_updated,error_message FROM data_sync_logs ORDER BY id DESC LIMIT 100")
    st.subheader("最近同步日志")
    st.dataframe(logs,use_container_width=True,hide_index=True)
    st.caption("请定期备份 data/gfm.db；不要公开分享包含 API 密钥的 .env 文件。")
