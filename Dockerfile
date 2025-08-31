FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# позволим подменять индекс PyPI во время сборки
ARG PIP_INDEX_URL=https://pypi.org/simple
RUN python -m pip config set global.index-url $PIP_INDEX_URL

WORKDIR /code

COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY . /code