import csv, os, re
from typing import Dict, Tuple, Optional, List
from .config import TEAM_SIZE, PARTICIPANTS_CSV, PARTICIPANTS_CSV_FALLBACK

# phone -> (first_name)
KNOWN: Dict[str, str] = {}

def norm_phone(s: str) -> str:
    if not s: return ""
    s = re.sub(r"[^\d+]", "", s.strip())
    if s.startswith("8") and len(s) == 11:
        s = "+7" + s[1:]
    if s.isdigit() and len(s) == 11 and s[0] == "7":
        s = "+" + s
    return s

def load_participants(path: str = PARTICIPANTS_CSV) -> None:
    KNOWN.clear()
    src = path if os.path.exists(path) else PARTICIPANTS_CSV_FALLBACK
    if not os.path.exists(src): return
    with open(src, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            p = norm_phone(row.get("phone",""))
            fn = (row.get("first_name") or "").strip()
            if p and fn:
                KNOWN[p] = fn

def only_first_name(user: dict) -> str:
    return (user.get("first_name") or "").strip() or "Без имени"

def format_roster(team: dict) -> str:
    team_name = team.get("team_name", "Команда")
    members: List[dict] = team.get("members") or []
    captain = team.get("captain")
    lines = []
    if captain:
        lines.append(f"👑 {only_first_name(captain)}")
    for m in members:
        if captain and m.get("user_id") == captain.get("user_id"):
            continue
        marker = "👑" if (m.get("role") or "").upper() == "CAPTAIN" else "•"
        lines.append(f"{marker} {only_first_name(m)}")
    count = len(members)
    body = "\n".join(lines) if lines else "_Пока нет участников._"
    return f"*Твоя команда:* {team_name}\n\nУчастников: *{count}* из *{TEAM_SIZE}*\n\n*Состав:*\n{body}"
