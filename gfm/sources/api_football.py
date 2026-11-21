import requests

BASE_URL = "https://v3.football.api-sports.io"

class ProviderError(RuntimeError):
    pass

def fetch_fixtures(api_key: str, date_from: str, date_to: str, league_id=None, season=None):
    if not api_key:
        raise ProviderError("缺少 API_FOOTBALL_KEY。请在 .env 中配置 API Key。")
    params = {"from": date_from, "to": date_to}
    if league_id not in (None, ""):
        params["league"] = int(league_id)
    if season not in (None, ""):
        params["season"] = int(season)
    try:
        response = requests.get(
            f"{BASE_URL}/fixtures", headers={"x-apisports-key": api_key},
            params=params, timeout=25,
        )
    except requests.RequestException as exc:
        raise ProviderError(f"网络请求失败：{exc}") from exc
    if response.status_code == 429:
        raise ProviderError("触发数据源限流（HTTP 429）。请检查每日/每分钟剩余额度。")
    if response.status_code in (401, 403):
        raise ProviderError("API Key 无效，或当前套餐无权访问该赛事/接口。")
    if not response.ok:
        raise ProviderError(f"数据源返回 HTTP {response.status_code}：{response.text[:300]}")
    payload = response.json()
    errors = payload.get("errors")
    if errors:
        raise ProviderError(f"API-Football 返回错误：{errors}")
    return payload.get("response", []), payload.get("paging", {})
