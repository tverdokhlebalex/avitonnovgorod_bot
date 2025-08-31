# ---- База ---------------------------------------------------------------
FROM python:3.11-slim-bookworm

# Можно оставить переменные — но решающее значение дадут флаги в pip ниже
ARG PIP_INDEX_URL=https://mirror.yandex.ru/mirrors/pypi/simple
ARG PIP_EXTRA_INDEX_URL=
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_EXTRA_INDEX_URL=${PIP_EXTRA_INDEX_URL} \
    PIP_DEFAULT_TIMEOUT=60 \
    PIP_RETRIES=20

# ---- APT: зеркала и базовые утилиты ------------------------------------
RUN set -eux; \
    rm -f /etc/apt/sources.list.d/* /etc/apt/sources.list.d/debian.sources || true; \
    printf '%s\n' \
      'deb http://mirror.yandex.ru/debian bookworm main contrib non-free non-free-firmware' \
      'deb http://mirror.yandex.ru/debian bookworm-updates main contrib non-free non-free-firmware' \
      'deb http://mirror.yandex.ru/debian bookworm-backports main contrib non-free non-free-firmware' \
      'deb http://mirror.yandex.ru/debian-security bookworm-security main contrib non-free' \
      > /etc/apt/sources.list; \
    apt-get -o Acquire::Retries=5 -o Acquire::http::Timeout=20 -o Acquire::https::Timeout=20 update -y; \
    apt-get install -y --no-install-recommends curl ca-certificates; \
    rm -rf /var/lib/apt/lists/*

# ---- Python deps --------------------------------------------------------
WORKDIR /code
COPY requirements.txt /tmp/requirements.txt

# Обновляем pip и ставим зависимости, добавляя несколько индексов (fallback в конце — PyPI)
RUN python -m pip install --upgrade pip && \
    pip install --no-cache-dir -r /tmp/requirements.txt \
      --index-url https://mirrors.aliyun.com/pypi/simple \
      --extra-index-url https://pypi.tuna.tsinghua.edu.cn/simple \
      --extra-index-url https://mirror.yandex.ru/mirrors/pypi/simple \
      --extra-index-url https://pypi.org/simple \
      --timeout 60 --retries 5

# ---- Код ----------------------------------------------------------------
COPY . /code