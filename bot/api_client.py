# bot/api_client.py
from __future__ import annotations

import logging
from typing import Any, Tuple

import aiohttp

from .config import get_http, api_url, APP_SECRET, json_headers


# ------------------------------ low-level HTTP -------------------------------

async def _read_json(r: aiohttp.ClientResponse) -> Any:
    """Безопасно читаем JSON; если не JSON — возвращаем сырой текст в {'raw': ...}."""
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
    """
    Единая обёртка над aiohttp.
    - Общая сессия из get_http()
    - Заголовок x-app-secret всегда
    - Если передан json (и не передан data) — добавляем JSON headers
    """
    s = await get_http()
    url = api_url(path)
    headers = {"x-app-secret": APP_SECRET}
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


# ------------------------------ Public API -----------------------------------

async def register_user(tg_id: int | str, phone: str, first_name: str):
    """
    POST /api/users/register (JSON)
    {tg_id, phone, first_name}
    """
    payload = {"tg_id": str(tg_id), "phone": phone, "first_name": first_name}
    return await _req_json("POST", "/api/users/register", json=payload)


async def team_by_tg(tg_id: int | str):
    """GET /api/teams/by-tg/{tg_id}"""
    return await _req_json("GET", f"/api/teams/by-tg/{tg_id}")


async def roster_by_tg(tg_id: int | str):
    """GET /api/teams/roster/by-tg/{tg_id}"""
    return await _req_json("GET", f"/api/teams/roster/by-tg/{tg_id}")


async def team_rename(tg_id: int | str, new_name: str):
    """
    POST /api/team/rename (JSON)
    {tg_id, new_name}
    """
    return await _req_json(
        "POST",
        "/api/team/rename",
        json={"tg_id": str(tg_id), "new_name": new_name},
    )


async def start_game(tg_id: int | str):
    """
    POST /api/game/start (form-data: tg_id)
    """
    fd = aiohttp.FormData()
    fd.add_field("tg_id", str(tg_id))
    return await _req_json("POST", "/api/game/start", data=fd)


async def current_checkpoint(tg_id: int | str):
    """
    GET /api/game/current?tg_id=...
    """
    return await _req_json("GET", "/api/game/current", params={"tg_id": str(tg_id)})


# совместимость со старым импортом
async def game_current(tg_id: int | str):
    return await current_checkpoint(tg_id)


async def submit_photo(tg_id: int | str, tg_file_id: str):
    """
    POST /api/game/photo (JSON)
    {tg_id, tg_file_id}
    """
    return await _req_json(
        "POST",
        "/api/game/photo",
        json={"tg_id": str(tg_id), "tg_file_id": tg_file_id},
    )


async def leaderboard():
    """GET /api/leaderboard"""
    return await _req_json("GET", "/api/leaderboard")


# ------------------------------ Admin API ------------------------------------

async def admin_pending():
    """GET /api/admin/proofs/pending"""
    return await _req_json("GET", "/api/admin/proofs/pending")


async def admin_approve(proof_id: int):
    """POST /api/admin/proofs/{proof_id}/approve"""
    return await _req_json("POST", f"/api/admin/proofs/{proof_id}/approve")


async def admin_reject(proof_id: int):
    """POST /api/admin/proofs/{proof_id}/reject"""
    return await _req_json("POST", f"/api/admin/proofs/{proof_id}/reject")


async def admin_get_team(team_id: int):
    """GET /api/admin/teams/{team_id}"""
    return await _req_json("GET", f"/api/admin/teams/{team_id}")


async def admin_list_teams():
    """GET /api/admin/teams"""
    return await _req_json("GET", "/api/admin/teams")


async def admin_set_captain(team_id: int, *, tg_id: int | str | None = None, user_id: int | None = None):
    """
    POST /api/admin/teams/{team_id}/set-captain (JSON)
    Body: { tg_id? | user_id? }
    """
    body: dict[str, Any] = {}
    if tg_id is not None:
        body["tg_id"] = str(tg_id)
    if user_id is not None:
        body["user_id"] = int(user_id)
    return await _req_json("POST", f"/api/admin/teams/{team_id}/set-captain", json=body)


async def admin_unset_captain(team_id: int):
    """POST /api/admin/teams/{team_id}/unset-captain"""
    return await _req_json("POST", f"/api/admin/teams/{team_id}/unset-captain")


async def admin_move_member(
    dest_team_id: int,
    *,
    tg_id: int | str | None = None,
    user_id: int | None = None,
    make_captain: bool = False,
):
    """
    POST /api/admin/members/move (JSON)
    Body: { dest_team_id, make_captain, tg_id? | user_id? }
    """
    body: dict[str, Any] = {"dest_team_id": int(dest_team_id), "make_captain": bool(make_captain)}
    if tg_id is not None:
        body["tg_id"] = str(tg_id)
    if user_id is not None:
        body["user_id"] = int(user_id)
    return await _req_json("POST", "/api/admin/members/move", json=body)


async def admin_team_rename(captain_tg_id: int | str, new_name: str):
    """
    POST /api/team/rename (JSON)
    Используем tg_id капитана.
    """
    return await _req_json(
        "POST",
        "/api/team/rename",
        json={"tg_id": str(captain_tg_id), "new_name": new_name},
    )


async def admin_lock_all():
    """POST /api/admin/teams/lock"""
    return await _req_json("POST", "/api/admin/teams/lock")


async def admin_unlock_all():
    """POST /api/admin/teams/unlock"""
    return await _req_json("POST", "/api/admin/teams/unlock")