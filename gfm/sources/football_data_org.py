from datetime import date
import requests

BASE_URL = "https://api.football-data.org/v4"

class ProviderError(RuntimeError):
    pass

def _get(path: str, token: str, params=None):
    if not token:
        raise ProviderError("缺少 FOOTBALL_DATA_TOKEN。请在 .env 中配置 API Token。")
    try:
        response = requests.get(
            f"{BASE_URL}{path}", headers={"X-Auth-Token": token},
            params=params or {}, timeout=25,
        )
    except requests.RequestException as exc:
        raise ProviderError(f"网络请求失败：{exc}") from exc
    if response.status_code == 429:
        raise ProviderError("触发数据源限流（HTTP 429）。请等待额度恢复后再同步。")
    if response.status_code in (401, 403):
        raise ProviderError("Token 无效，或当前套餐无权访问该赛事/接口。")
    if not response.ok:
        raise ProviderError(f"数据源返回 HTTP {response.status_code}：{response.text[:300]}")
    return response.json()

def fetch_competitions(token: str):
    payload = _get("/competitions", token)
    return payload.get("competitions", [])

def fetch_matches(token: str, competition_code: str, date_from: date, date_to: date):
    payload = _get(
        f"/competitions/{competition_code}/matches", token,
        {"dateFrom": date_from.isoformat(), "dateTo": date_to.isoformat()},
    )
    return payload.get("matches", [])
