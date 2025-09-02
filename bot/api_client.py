import json, logging, aiohttp
from typing import Any
from .config import get_http, api_url, APP_SECRET, json_headers

async def _req_json(method: str, path: str, *, data: Any | None = None, form: dict | None = None) -> tuple[int, Any]:
    s = await get_http()
    url = api_url(path)
    try:
        if method == "GET":
            async with s.get(url, headers={"x-app-secret": APP_SECRET}) as r:
                txt = await r.text()
        elif form is not None:
            async with s.post(url, headers={"x-app-secret": APP_SECRET}, data=form) as r:
                txt = await r.text()
        else:
            async with s.post(url, headers=json_headers(), json=data) as r:
                txt = await r.text()
        try:
            payload = json.loads(txt) if txt else None
        except json.JSONDecodeError:
            payload = {"raw": txt}
        return r.status, payload
    except aiohttp.ClientError as e:
        logging.error("%s %s failed: %r", method, url, e)
        raise
async def game_current(tg_id: int) -> tuple[int, dict]:
    """
    GET /api/game/current?tg_id=<tg_id>
    Возвращает:
      { finished: bool, checkpoint: { id, order_num, title, riddle, photo_hint, total } | None }
    """
    from .config import API_BASE, APP_SECRET
    import aiohttp

    url = f"{API_BASE}/api/game/current"
    params = {"tg_id": str(tg_id)}
    headers = {"x-app-secret": APP_SECRET}

    async with aiohttp.ClientSession() as s:
        async with s.get(url, params=params, headers=headers) as r:
            st = r.status
            try:
                data = await r.json()
            except Exception:
                data = {"detail": await r.text()}
            return st, data
        
        
# ---- публичные обёртки ----
async def team_by_tg(tg_id: int | str):         return await _req_json("GET",  f"/api/teams/by-tg/{tg_id}")
async def roster_by_tg(tg_id: int | str):       return await _req_json("GET",  f"/api/teams/roster/by-tg/{tg_id}")
async def register_user(tg_id: int | str, phone: str, first_name: str):
    return await _req_json("POST", "/api/users/register", data={"tg_id": str(tg_id), "phone": phone, "first_name": first_name, "last_name": None})
async def team_rename(tg_id: int | str, new_name: str):
    return await _req_json("POST", "/api/team/rename", data={"tg_id": str(tg_id), "new_name": new_name})
async def start_game(tg_id: int | str):         return await _req_json("POST", "/api/game/start", form={"tg_id": str(tg_id)})
async def current_checkpoint(tg_id: int | str): return await _req_json("GET",  f"/api/game/current?tg_id={tg_id}")
async def submit_photo(tg_id: int | str, file_id: str):
    return await _req_json("POST", "/api/game/photo", data={"tg_id": str(tg_id), "tg_file_id": file_id})
async def leaderboard():                         return await _req_json("GET",  "/api/leaderboard")
