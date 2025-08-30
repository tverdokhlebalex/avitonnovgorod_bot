# QuestBot MVP — Starter

Monorepo: FastAPI + SQLAdmin (веб-админка) + Aiogram (бот), Postgres, Redis.

## Быстрый старт
1) Скопируйте `.env.example` → `.env` и заполните `BOT_TOKEN` и `DB_*`.
2) `docker compose up --build` (создаст БД и поднимет сервисы).
3) Админка: `http://localhost:8000/admin`.
4) Бот: пока polling; подключение webhook добавим позже.

## Схема данных
users, teams, team_members, quests, checkpoints, tasks, submissions, penalties, appeals, tokens_used, audit_log
# avitonnovgorod_bot
