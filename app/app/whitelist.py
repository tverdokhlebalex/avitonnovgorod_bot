# app/app/whitelist.py
import csv
import os
import threading
from pathlib import Path
from typing import Optional, Dict

STRICT = os.getenv("STRICT_WHITELIST", "false").strip().lower() in {"1","true","yes","on"}
CSV_PATH = os.getenv("WHITELIST_PATH", "./data/participants_template.csv")

_lock = threading.RLock()
_data: Dict[str, Dict] = {}
_loaded = False

def _norm_phone(phone: str) -> Optional[str]:
    if not phone:
        return None
    p = "".join(ch for ch in phone if ch.isdigit() or ch == "+")
    # допускаем вход: 8ХХХ..., 7ХХХ..., +7ХХХ..., 9ХХХ...
    if p.startswith("+"):
        pass
    elif p.startswith("8") and len(p) == 11:
        p = "+7" + p[1:]
    elif p.startswith("7") and len(p) == 11:
        p = "+" + p
    elif p.startswith("9") and len(p) == 10:
        p = "+7" + p
    # быстрая валидация
    if not (p.startswith("+7") and len(p) == 12 and p[1:].isdigit()):
        return None
    return p

def _load_locked() -> None:
    global _data, _loaded
    _data = {}
    path = Path(CSV_PATH)
    if not path.exists():
        _loaded = True
        return
    with path.open("r", encoding="utf-8") as f:
        rd = csv.DictReader(f)
        # Ожидаем столбцы: phone,first_name
        for row in rd:
            phone = _norm_phone(row.get("phone","").strip())
            if not phone:
                continue
            first_name = (row.get("first_name") or "").strip()
            _data[phone] = {"first_name": first_name, "phone": phone}
    _loaded = True

def ensure_loaded() -> None:
    with _lock:
        if not _loaded:
            _load_locked()

def reload() -> int:
    with _lock:
        _load_locked()
        return len(_data)

def lookup(phone: str) -> Optional[Dict]:
    ensure_loaded()
    p = _norm_phone(phone)
    if not p:
        return None
    return _data.get(p)

def is_allowed(phone: str) -> bool:
    """true в нон-строгом режиме всегда, в строгом — только если есть совпадение."""
    if not STRICT:
        return True
    return lookup(phone) is not None

def norm_phone(phone: str) -> Optional[str]:
    return _norm_phone(phone)

def stats() -> Dict:
    ensure_loaded()
    return {"strict": STRICT, "size": len(_data), "path": CSV_PATH}