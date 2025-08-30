# app/app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import engine
from .models import Base

# Роуты API и WebApp
from app.api import router as api_router          # /api/...
from app.webapp import router as webapp_api       # /api/webapp/...
from app.webapp import page_router as webapp_page # /webapp (HTML)

app = FastAPI(title="QuestBot MVP")

# Основные API-роуты
app.include_router(api_router)

# WebApp: HTML-страница на /webapp и JSON-эндпоинты на /api/webapp/...
app.include_router(webapp_page)
app.include_router(webapp_api)

# CORS (можно сузить allow_origins при необходимости)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    try:
        from .admin import mount_admin  # type: ignore
        mount_admin(app)
    except Exception:
        pass

@app.get("/health", tags=["core"])
def health():
    return {"status": "ok"}