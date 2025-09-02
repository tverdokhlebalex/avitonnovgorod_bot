# /code/scripts/seed_routes.py
from __future__ import annotations

import os
import sys
from typing import List, Dict, Any
from pathlib import Path

# --- sys.path так, чтобы import app.* работал и внутри контейнера, и локально
ROOT = Path(__file__).resolve().parents[1]  # /code
APP_DIR = ROOT / "app"
for p in (str(ROOT), str(APP_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from sqlalchemy import func
from app.database import SessionLocal
from app import models

DEFAULT_PHOTO_HINT = "Вся команда + фото разгаданной локации. Снимайте с нижней точки."

DATA: Dict[str, Dict[str, Any]] = {
    "A": {
        "title": "Маршрут A",
        "checkpoints": [
            {
                "order_num": 1,
                "title": "Задание A1",
                "riddle": (
                    "Самая колоритная, многоавторская и идейная подворотня Нижнего. "
                    "Улица созвучна с именем виртуального ассистента, а номер дома равен "
                    "количеству внутренних сообществ инженеров в Авито — 3.\n\n"
                    "Ждём ваше фото на этой точке маршрута :)"
                ),
                "photo_hint": DEFAULT_PHOTO_HINT,
            },
            {
                "order_num": 2,
                "title": "Задание A2",
                "riddle": (
                    "Это не терминал, но в нём тоже бывает «эхо».\n\n"
                    "Она не подключена к серверу, но ловит каждый звук.\n"
                    "Ты не запустишь в ней скрипт, но можешь услышать импровизацию.\n"
                    "Она не логирует, но отлично передаёт,\n"
                    "и если инженеры собираются на офлайн-митап — это место подходит идеально.\n\n"
                    "Никакой отказоустойчивости не нужно —\n"
                    "работает без электричества, аптайм — 100% при хорошей погоде.\n\n"
                    "Ждём ваше фото на этой точке маршрута :)"
                ),
                "photo_hint": DEFAULT_PHOTO_HINT,
            },
            {
                "order_num": 3,
                "title": "Задание A3",
                "riddle": (
                    "ctrl+alt+t + X, где X — некий курс от Авито/3.\n\n"
                    "Ждём ваше фото на этой точке маршрута :)"
                ),
                "photo_hint": DEFAULT_PHOTO_HINT,
            },
            {
                "order_num": 4,
                "title": "Задание A4",
                "riddle": (
                    "А теперь вам нужно найти место, где живут с недавнего времени наши маскоты — "
                    "перебраться сюда им помог Максим Трулов. Место совсем близко, достаточно просто оглянуться.\n\n"
                    "Ждём ваше фото на этой точке маршрута :)"
                ),
                "photo_hint": DEFAULT_PHOTO_HINT,
            },
            {
                "order_num": 5,
                "title": "Задание A5",
                "riddle": (
                    "В «Недвижимости» мы различаем: многоквартирные дома и отдельные городские дома "
                    "под одного владельца. Перед вами второй тип; на фасаде — год середины XIX века. "
                    "Как назвать локацию одним каноничным именем? Эта локация совсем близко.\n\n"
                    "Ждём ваше фото на этой точке маршрута :)"
                ),
                "photo_hint": DEFAULT_PHOTO_HINT,
            },
        ],
    },
    "B": {
        "title": "Маршрут B",
        "checkpoints": [
            {
                "order_num": 1,
                "title": "Задание B1",
                "riddle": (
                    "Если бы у нас не было интернета, мы бы точно нашли место в Нижнем Новгороде, "
                    "где можно было бы развивать наш бизнес. Многие с радостью готовы торговать оффлайн — "
                    "особенно по субботам под открытым небом. Где именно? Совсем недалеко от нашей стартовой точки.\n\n"
                    "Ждём ваше фото на этой точке маршрута :)"
                ),
                "photo_hint": DEFAULT_PHOTO_HINT,
            },
            {
                "order_num": 2,
                "title": "Задание B2",
                "riddle": (
                    "В наших ценностях есть пункт: «Проверяем решения и процессы на здравый смысл и пользу». "
                    "В этом мы бы не сошлись во взглядах с одним героем, который «принимает реальность такой, "
                    "какой её преподносят». Вам нужно найти неподалёку отсюда место, с которым связан этот герой.\n\n"
                    "Ждём ваше фото на этой точке маршрута :)"
                ),
                "photo_hint": DEFAULT_PHOTO_HINT,
            },
            {
                "order_num": 3,
                "title": "Задание B3",
                "riddle": "Jupyter notebook.\n\nЖдём ваше фото на этой точке маршрута :)",
                "photo_hint": DEFAULT_PHOTO_HINT,
            },
            {
                "order_num": 4,
                "title": "Задание B4",
                "riddle": "Здесь больше нет огня.\n\nЖдём ваше фото на этой точке маршрута :)",
                "photo_hint": DEFAULT_PHOTO_HINT,
            },
        ],
    },
    "C": {
        "title": "Маршрут C",
        "checkpoints": [
            {
                "order_num": 1,
                "title": "Задание C1",
                "riddle": (
                    "Вспомним основы сетевых технологий. Нужен номер порта для FTP и тип DNS-записи для IPv4. "
                    "Запишите их подряд — это будет номер и литера дома. А само название улицы — городской "
                    "«бордюр у воды» с родительным от Волга, но в нижнем ярусе.\n\n"
                    "Ждём ваше фото на этой точке маршрута :)"
                ),
                "photo_hint": DEFAULT_PHOTO_HINT,
            },
            {
                "order_num": 2,
                "title": "Задание C2",
                "riddle": (
                    "В Авито похожие запросы склеиваются в один кластер. Слушайте набор: колядки, подарки, "
                    "Санта Клаус, звезда на ёлке, сочельник. Какое слово объединяет эти понятия и как звучит "
                    "улица с этим корнем в названии? А чтобы узнать номер дома, вам нужно к количеству вертикалей "
                    "в Авито прибавить единицу.\n\n"
                    "Ждём ваше фото на этой точке маршрута :)"
                ),
                "photo_hint": DEFAULT_PHOTO_HINT,
            },
            {
                "order_num": 3,
                "title": "Задание C3",
                "riddle": (
                    "Раньше у Авито было X уровней инженеров, но сейчас у нас их Y (подробнее — в developer profile).\n\n"
                    "X−1 . Y+3\n\n"
                    "Вместе — знаковое событие. Вам нужно место, которое было открыто в эту же дату "
                    "и непосредственно связано с этим событием.\n\n"
                    "Ждём ваше фото на этой точке маршрута :)"
                ),
                "photo_hint": DEFAULT_PHOTO_HINT,
            },
            {
                "order_num": 4,
                "title": "Задание C4",
                "riddle": (
                    "Неподалёку от вас есть наш потенциальный пользователь. Она с лёгкостью могла бы разместить "
                    "объявление на Авито и попала бы в категорию «продукты питания». Нужно сделать фото с ней.\n\n"
                    "Ждём ваше фото на этой точке маршрута :)"
                ),
                "photo_hint": DEFAULT_PHOTO_HINT,
            },
        ],
    },
}

# ---------- утилиты безопасной установки полей ----------

def _set_first_existing_attr(obj, names: List[str], value: Any) -> None:
    for n in names:
        if hasattr(obj.__class__, n):
            setattr(obj, n, value)
            return

def _first_existing_ctor_kwargs(model, pairs: List[tuple[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for name, value in pairs:
        if hasattr(model, name):
            out[name] = value
    return out


# ---------- сидирование ----------

def upsert_route(session, code: str, title: str) -> models.Route:
    route = session.query(models.Route).filter(models.Route.code == code).one_or_none()
    if route:
        _set_first_existing_attr(route, ["title", "name"], title)
        session.flush()
        return route
    kwargs = _first_existing_ctor_kwargs(models.Route, [("code", code), ("title", title), ("name", title)])
    if "code" not in kwargs:  # на всякий
        kwargs["code"] = code
    route = models.Route(**kwargs)
    session.add(route)
    session.flush()
    return route


def replace_checkpoints(session, route: models.Route, checkpoints: List[Dict[str, Any]]) -> None:
    # Удаляем proof'ы и чекпоинты маршрута
    cp_ids = [row[0] for row in session.query(models.Checkpoint.id).filter(models.Checkpoint.route_id == route.id).all()]
    if cp_ids:
        session.query(models.Proof).filter(models.Proof.checkpoint_id.in_(cp_ids)).delete(synchronize_session=False)
        session.query(models.Checkpoint).filter(models.Checkpoint.id.in_(cp_ids)).delete(synchronize_session=False)
        session.flush()

    # Создаём новые чекпоинты
    for cp in sorted(checkpoints, key=lambda x: int(x["order_num"])):
        obj = models.Checkpoint(route_id=route.id, order_num=int(cp["order_num"]))
        _set_first_existing_attr(obj, ["title", "name"], (cp.get("title") or "").strip())
        _set_first_existing_attr(obj, ["riddle", "description", "text"], (cp.get("riddle") or "").strip())
        _set_first_existing_attr(obj, ["photo_hint", "hint"], (cp.get("photo_hint") or DEFAULT_PHOTO_HINT).strip())
        session.add(obj)
    session.flush()


def maybe_assign_routes_to_teams(session) -> None:
    """
    Если ASSIGN_EXISTING_TEAMS=1 — назначаем маршруты командам без route_id по кругу A→B→C…
    current_order_num ставим = 1 (столбец у тебя NOT NULL, DEFAULT 1).
    """
    if os.getenv("ASSIGN_EXISTING_TEAMS", "").strip().lower() not in ("1", "true", "yes", "on"):
        return

    routes = (
        session.query(models.Route)
        .filter(models.Route.code.in_(list(DATA.keys())))
        .order_by(models.Route.code.asc())
        .all()
    )
    if not routes:
        return

    teams = (
        session.query(models.Team)
        .filter(models.Team.route_id.is_(None))
        .order_by(models.Team.id.asc())
        .all()
    )
    i = 0
    for t in teams:
        t.route_id = routes[i % len(routes)].id
        # ВАЖНО: не None, а 1
        if hasattr(t.__class__, "current_order_num"):
            t.current_order_num = 1
        session.flush()
        i += 1


def main() -> None:
    session = SessionLocal()
    try:
        for code, payload in DATA.items():
            route = upsert_route(session, code=code.upper(), title=payload["title"])
            replace_checkpoints(session, route=route, checkpoints=payload["checkpoints"])

        maybe_assign_routes_to_teams(session)

        session.commit()
        print("OK: routes/checkpoints seeded")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
