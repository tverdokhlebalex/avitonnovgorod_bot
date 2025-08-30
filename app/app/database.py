# app/app/database.py
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Если у тебя psycopg3 (в requirements: psycopg[binary]), оставляй так:
DEFAULT_DSN = "postgresql+psycopg://postgres:postgres@db:5432/postgres"
# Если используешь psycopg2-binary — поменяй на:
# DEFAULT_DSN = "postgresql+psycopg2://postgres:postgres@db:5432/postgres"

DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_DSN)

engine = create_engine(DATABASE_URL, future=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)
Base = declarative_base()

# То самое, чего не хватало:
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
