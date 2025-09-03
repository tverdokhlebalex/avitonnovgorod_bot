import os, re, aiohttp, logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN or not re.match(r"^\d+:[\w-]+$", BOT_TOKEN):
    raise SystemExit("BOT_TOKEN отсутствует или некорректен")


ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(";",",").split(",") if x.strip().isdigit()}
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0") or 0)
ADMIN_POLL_SECONDS = int(os.getenv("ADMIN_POLL_SECONDS", "5"))
PROOFS_DIR = os.getenv("PROOFS_DIR", "/code/data/proofs")

API_BASE = (os.getenv("API_BASE") or os.getenv("API_URL", "http://app:8000")).rstrip("/")
APP_SECRET = os.getenv("APP_SECRET", "change-me-please")
TEAM_SIZE = int(os.getenv("TEAM_SIZE", "7"))
STRICT_WHITELIST = os.getenv("STRICT_WHITELIST", "true").lower() in ("1","true","yes","y")

PARTICIPANTS_CSV = os.getenv("PARTICIPANTS_CSV", "/code/data/participants.csv")
PARTICIPANTS_CSV_FALLBACK = "/code/data/participants_template.csv"

CLIENT_TIMEOUT = aiohttp.ClientTimeout(total=20, connect=5, sock_connect=5, sock_read=15)
ADMIN_USER_IDS = {
    int(x) for x in os.getenv("ADMIN_USER_IDS", "").replace(" ", "").split(",") if x
}
# WebApp
WEBAPP_URL = (os.getenv("WEBAPP_URL") or f"{API_BASE}/webapp").strip()
def build_webapp_url(tg_id: int | str) -> str:
    url = WEBAPP_URL
    low = url.lower()
    # dev-режим для http/localhost
    if low.startswith("http://") or "localhost" in low or "127.0.0.1" in low:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}dev_tg={tg_id}"
    return url

# HTTP session
HTTP: aiohttp.ClientSession | None = None
async def get_http() -> aiohttp.ClientSession:
    global HTTP
    if HTTP is None or HTTP.closed:
        HTTP = aiohttp.ClientSession(timeout=CLIENT_TIMEOUT)
    return HTTP

def api_url(p: str) -> str:
    return f"{API_BASE}{p}"

def json_headers() -> dict:
    return {"x-app-secret": APP_SECRET, "Content-Type": "application/json"}