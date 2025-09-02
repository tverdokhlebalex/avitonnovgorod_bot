# --- runtime ---
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /code

# кладём локальные "колёса" внутрь образа
COPY wheelhouse/ /opt/wheels/
COPY requirements.txt /tmp/requirements.txt

# ставим ТОЛЬКО из /opt/wheels (без сети)
RUN pip install --no-index --find-links=/opt/wheels -r /tmp/requirements.txt

# затем код
COPY . /code