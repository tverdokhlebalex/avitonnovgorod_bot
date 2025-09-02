# bot/api_client.py
import logging
from typing import Any, Tuple
import aiohttp

from .config import get_http, api_url, APP_SECRET, json_headers

async def _read_json(r: aiohttp.ClientResponse) -> Any:
    try:
        return await r.json(content_type=None)
    except Exception:
        try:
            txt = await r.text()
        except Exception:
            txt = ""
        return {"raw": txt}

async def _req_json(
    method: str,
    path: str,
    *,
    params: dict | None = None,
    json: Any | None = None,
    data: Any | None = None,
) -> Tuple[int, Any]:
    """Единый HTTP-клиент. Используем общую сессию из get_http()."""
    s = await get_http()
    url = api_url(path)
    headers = {"x-app-secret": APP_SECRET}
    # если шлём JSON — добавим правильные заголовки
    if json is not None and data is None:
        headers.update(json_headers())
    try:
        if method == "GET":
            async with s.get(url, params=params, headers=headers) as r:
                return r.status, await _read_json(r)
        elif method == "POST":
            async with s.post(url, params=params, headers=headers, json=json, data=data) as r:
                return r.status, await _read_json(r)
        elif method == "PATCH":
            async with s.patch(url, params=params, headers=headers, json=json, data=data) as r:
                return r.status, await _read_json(r)
        else:
            raise RuntimeError(f"Unsupported method: {method}")
    except aiohttp.ClientError as e:
        logging.error("%s %s failed: %r", method, url, e)
        return 0, {"detail": "network_error"}
    except Exception:
        logging.exception("%s %s unexpected error", method, url)
        return 0, {"detail": "unexpected_error"}


# ---------- Public wrappers ----------

async def register_user(tg_id: int | str, phone: str, first_name: str):
    # /api/users/register — ждёт JSON
    payload = {"tg_id": str(tg_id), "phone": phone, "first_name": first_name}
    return await _req_json("POST", "/api/users/register", json=payload)

async def team_by_tg(tg_id: int | str):
    return await _req_json("GET", f"/api/teams/by-tg/{tg_id}")

async def roster_by_tg(tg_id: int | str):
    return await _req_json("GET", f"/api/teams/roster/by-tg/{tg_id}")

async def team_rename(tg_id: int | str, new_name: str):
    # /api/team/rename — JSON
    return await _req_json("POST", "/api/team/rename",
                           json={"tg_id": str(tg_id), "new_name": new_name})

async def start_game(tg_id: int | str):
    # /api/game/start — form-data (tg_id)
    fd = aiohttp.FormData()
    fd.add_field("tg_id", str(tg_id))
    return await _req_json("POST", "/api/game/start", data=fd)

async def current_checkpoint(tg_id: int | str):
    # /api/game/current — GET с ?tg_id=
    return await _req_json("GET", "/api/game/current", params={"tg_id": str(tg_id)})

# совместимость со старым импортом в captain.py
async def game_current(tg_id: int | str):
    return await current_checkpoint(tg_id)

async def submit_photo(tg_id: int | str, tg_file_id: str):
    # /api/game/photo — JSON
    return await _req_json("POST", "/api/game/photo",
                           json={"tg_id": str(tg_id), "tg_file_id": tg_file_id})

async def leaderboard():
    return await _req_json("GET", "/api/leaderboard")