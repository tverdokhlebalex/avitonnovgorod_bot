#!/usr/bin/env bash
set -euo pipefail

# ===== Параметры (можно переопределить в окружении) =====
API_URL="${API_URL:-http://127.0.0.1:8000}"
APP_SECRET="${APP_SECRET:-AvitoCode}"
ADMIN_SECRET="${ADMIN_SECRET:-AvitoAdmin}"  # зарезервировано

TG="${TG:-721573769}"
PHONE="${PHONE:-+79890000000}"
FN="${FN:-Александр}"
LN="${LN:-Твердохлеб}"   # передаём для совместимости (беку достаточно first_name)

TASK_CODE="${TASK_CODE:-demo}"
TASK_TITLE="${TASK_TITLE:-Демо задача}"
TASK_POINTS="${TASK_POINTS:-3}"

TEAM_SIZE="${TEAM_SIZE:-7}"           # для отображения статуса укомплектованности

MAX_WAIT="${MAX_WAIT:-45}"            # сек. ждать /health
CONNECT_TO="${CONNECT_TO:-2}"         # сек. curl connect-timeout

# ===== Проверки окружения =====
if ! command -v jq >/dev/null 2>&1; then
  echo "Требуется jq (brew install jq / apt-get install jq)"; exit 1
fi
if ! command -v base64 >/dev/null 2>&1; then
  echo "Нужен base64"; exit 1
fi

echo
echo "==> Параметры"
echo "API_URL=$API_URL"
echo "APP_SECRET=$APP_SECRET"
echo "TG=$TG PHONE=$PHONE NAME=$LN $FN"
echo "TASK: $TASK_CODE ($TASK_TITLE, $TASK_POINTS очк.)"

# ===== Автоподмена API_URL, если указан http://app:8000 и мы на хосте =====
if [[ "$API_URL" =~ ^http://app: ]]; then
  if ! curl -fsS --connect-timeout "$CONNECT_TO" "$API_URL/health" >/dev/null 2>&1; then
    echo "! '$API_URL' недоступен с хоста. Переходим на http://127.0.0.1:8000"
    API_URL="http://127.0.0.1:8000"
  fi
fi

hdr_app=(-H "x-app-secret: $APP_SECRET")
json_ct=(-H "Content-Type: application/json")

# ===== Ждём /health c таймаутом =====
echo
echo "==> Ждём /health ($API_URL/health)"
deadline=$(( $(date +%s) + MAX_WAIT ))
until curl -fsS --connect-timeout "$CONNECT_TO" --max-time 5 "$API_URL/health" >/dev/null 2>&1; do
  if (( $(date +%s) >= deadline )); then
    echo "✗ API не поднялся за ${MAX_WAIT}с по адресу $API_URL/health"
    echo "  Проверь: docker compose ps, docker compose logs app"
    exit 1
  fi
  sleep 1
done
curl -sS "$API_URL/health" && echo

# ===== Разблокируем команды =====
echo
echo "==> Разблокируем команды"
curl -sS -X POST "${hdr_app[@]}" "$API_URL/api/admin/teams/unlock" >/dev/null
CNT=$(curl -sS "${hdr_app[@]}" "$API_URL/api/admin/teams" | jq 'length')
echo "Команд: $CNT"
echo "✓ Команды разблокированы"

# ===== Создаём/находим задачу =====
echo
echo "==> Создаём (или находим) задачу"
CREATE_PAYLOAD=$(jq -n --arg c "$TASK_CODE" --arg t "$TASK_TITLE" --argjson p "$TASK_POINTS" \
  '{code:$c, title:$t, description:null, points:$p, is_active:true, order:1}')

CREATE_RES=$(curl -sS -X POST "${hdr_app[@]}" "${json_ct[@]}" \
  "$API_URL/api/admin/tasks" -d "$CREATE_PAYLOAD" || true)

if echo "$CREATE_RES" | jq -e '.id' >/dev/null 2>&1; then
  echo "$CREATE_RES" | jq .
  TASK_ID=$(echo "$CREATE_RES" | jq -r '.id')
  echo "✓ Создана: id=$TASK_ID"
else
  echo "! Создание не удалось (возможно, уже есть). Ищем по коду…"
  LIST=$(curl -sS "${hdr_app[@]}" "$API_URL/api/admin/tasks")
  TASK_ID=$(echo "$LIST" | jq -r --arg c "$TASK_CODE" '.[] | select(.code==$c) | .id' | head -n1)
  if [[ -z "$TASK_ID" || "$TASK_ID" == "null" ]]; then
    echo "✗ Не нашли задачу $TASK_CODE"; echo "$LIST"; exit 1
  fi
  echo "✓ Найдена: id=$TASK_ID"
fi

# ===== Регистрируем игрока =====
echo
echo "==> Регистрируем игрока"
REG_PAYLOAD=$(jq -n --arg tg "$TG" --arg ph "$PHONE" --arg fn "$FN" --arg ln "$LN" \
  '{tg_id:$tg, phone:$ph, first_name:$fn, last_name:$ln}')

REG_RES=$(curl -sS -X POST "${hdr_app[@]}" "${json_ct[@]}" \
  "$API_URL/api/users/register" -d "$REG_PAYLOAD")

echo "$REG_RES" | jq .
TEAM_ID=$(echo "$REG_RES" | jq -r '.team_id')
TEAM_NAME=$(echo "$REG_RES" | jq -r '.team_name')
echo "✓ Зарегистрирован → team #$TEAM_ID ($TEAM_NAME)"

# ===== Назначаем капитана =====
echo
echo "==> Назначаем капитана (этот TG) в команде #$TEAM_ID"
SC_PAYLOAD=$(jq -n --arg tg "$TG" '{tg_id:$tg}')
SC_RES=$(curl -sS -X POST "${hdr_app[@]}" "${json_ct[@]}" \
  "$API_URL/api/admin/teams/$TEAM_ID/set-captain" -d "$SC_PAYLOAD")
echo "$SC_RES" | jq '{team_id: .team_id, team_name: .team_name, captain: (if has("captain") and .captain != null then .captain else null end)}'

# ===== Переименование команды (1 раз до старта) =====
echo
echo "==> Переименование команды капитаном (1 раз)"
NEW_NAME="Команда №${TEAM_ID} — E2E $(date +%H%M%S)"
RN_PAYLOAD=$(jq -n --arg tg "$TG" --arg n "$NEW_NAME" '{tg_id:$tg, new_name:$n}')
RN_RES=$(curl -sS -X POST "${hdr_app[@]}" "${json_ct[@]}" \
  "$API_URL/api/teams/rename" -d "$RN_PAYLOAD" || true)

if echo "$RN_RES" | jq -e '.ok' >/dev/null 2>&1; then
  echo "$RN_RES" | jq .
  echo "✓ Новое имя: $(echo "$RN_RES" | jq -r '.team_name')"
else
  echo "! Переименование не выполнено (возможно, уже использовано). Ответ:"
  echo "$RN_RES"
fi

# ===== Старт квеста (капитан) =====
echo
echo "==> Старт квеста капитаном"
START_RES=$(curl -sS -X POST "${hdr_app[@]}" \
  -F "tg_id=$TG" \
  "$API_URL/api/game/start" || true)

if echo "$START_RES" | jq -e '.ok' >/dev/null 2>&1; then
  echo "$START_RES" | jq .
  echo "✓ Квест запущен"
else
  # если эндпоинт ещё не внедрён — будет HTML/404; защитимся
  if echo "$START_RES" | jq . >/dev/null 2>&1; then
    MSG=$(echo "$START_RES" | jq -r '.message // .detail // empty')
    if [[ -n "$MSG" ]]; then
      echo "! Старт квеста: $MSG"
    else
      echo "! Старт квеста: см. ответ ниже"
      echo "$START_RES" | jq .
    fi
  else
    echo "! /api/game/start пока недоступен; пропускаем шаг"
  fi
fi

# ===== Ростер (без цветов/маршрутов) =====
echo
echo "==> Ростер моей команды"
ROSTER=$(curl -sS "${hdr_app[@]}" "$API_URL/api/teams/roster/by-tg/$TG")
echo "$ROSTER" | jq .
CAP=$(echo "$ROSTER" | jq -r 'if .captain and .captain != null then (.captain.last_name + " " + .captain.first_name) else "—" end')
MEMS=$(echo "$ROSTER" | jq -r '.members | length')
echo "Капитан: $CAP | Участников: $MEMS из ${TEAM_SIZE}"

# ===== Скан 1: QR (авто-апрув) =====
echo
echo "==> Скан 1: $TASK_CODE (QR)"
SCAN_PAYLOAD=$(jq -n --arg tg "$TG" --arg code "$TASK_CODE" '{tg_id:$tg, code:$code}')
SCAN1=$(curl -sS -X POST "${hdr_app[@]}" "${json_ct[@]}" \
  "$API_URL/api/game/scan" -d "$SCAN_PAYLOAD" || true)
if echo "$SCAN1" | jq . >/dev/null 2>&1; then
  echo "$SCAN1" | jq .
else
  echo "✗ /game/scan #1 вернул не-JSON:"
  printf '%s\n' "$SCAN1"
  exit 1
fi

# ===== Фото-доказательство (уходит в модерацию) =====
echo
echo "==> Отправляем фото-доказательство (в модерацию)"
TMP_PHOTO="$(mktemp /tmp/proofXXXX.jpg)"
# 1x1 JPEG (валидный), из встроенного base64
base64 -d >"$TMP_PHOTO" <<'B64'
/9j/4AAQSkZJRgABAQAAAQABAAD/2wCEAAkGBxAQEA8PEA8QDw8QDw8PDw8PDw8PDw8QFREWFhUR
FhUYHSggGBolGxYVITEhJSkrLi4uFx8zODMsNygtLisBCgoKDg0OGxAQGi0fHyItLS0tLS0tLS0t
LS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLf/AABEIAAEAAQMBIgACEQED
EQH/xAAbAAEAAgMBAQAAAAAAAAAAAAAABAUCAwYBB//EADsQAAEDAgMFBgQEBwAAAAAAAAEAAgMR
BBIhMUEFUWGRExQiMoGhscHR8BQjQlJy0fEkQ1NygrLx/8QAGQEBAQEBAQEAAAAAAAAAAAAAAQID
AAT/xAAhEQEBAQABBAMAAAAAAAAAAAAAARECIRIxQRMUUf/aAAwDAQACEQMRAD8A8YgAAAAAAAAA
AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB//Z
B64

PHOTO_RES=$(curl -sS -X POST "${hdr_app[@]}" \
  -F "tg_id=$TG" -F "code=$TASK_CODE" -F "file=@$TMP_PHOTO;type=image/jpeg" \
  "$API_URL/api/game/submit-photo" || true)

if echo "$PHOTO_RES" | jq -e '.ok' >/dev/null 2>&1; then
  echo "$PHOTO_RES" | jq .
  PROG_ID=$(echo "$PHOTO_RES" | jq -r '.progress_id')
else
  echo "✗ submit-photo ответил неуспешно:"
  echo "$PHOTO_RES"
  PROG_ID=""
fi

# ===== Список PENDING в модерации =====
echo
echo "==> PENDING на модерации (первые 3)"
curl -sS "${hdr_app[@]}" "$API_URL/api/admin/proofs/pending" | jq '.[:3]'

# ===== Аппрувнем наш (если id получили) =====
if [[ -n "${PROG_ID:-}" && "$PROG_ID" != "null" ]]; then
  echo
  echo "==> Аппрувим прогресс #$PROG_ID"
  APR=$(curl -sS -X POST "${hdr_app[@]}" "$API_URL/api/admin/proofs/$PROG_ID/approve" || true)
  echo "$APR" | jq .
fi

# ===== Скан 2 (повтор) =====
echo
echo "==> Скан 2 (повтор): $TASK_CODE"
SCAN2=$(curl -sS -X POST "${hdr_app[@]}" "${json_ct[@]}" \
  "$API_URL/api/game/scan" -d "$SCAN_PAYLOAD" || true)
if echo "$SCAN2" | jq . >/dev/null 2>&1; then
  echo "$SCAN2" | jq .
else
  echo "✗ /game/scan #2 вернул не-JSON:"
  printf '%s\n' "$SCAN2"
fi

# ===== Лидерборд (если эндпоинт уже реализован) =====
echo
echo "==> Лидерборд (если доступен)"
LB=$(curl -sS "${hdr_app[@]}" "$API_URL/api/leaderboard" || true)
if echo "$LB" | jq . >/dev/null 2>&1; then
  echo "$LB" | jq '.[0:10]'
else
  echo "(пропускаем) /api/leaderboard пока недоступен"
fi

echo
echo "✓ E2E прогон завершён"