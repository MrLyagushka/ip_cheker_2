# ip_cheker_2 — Telegram-бот проверки доступности IP
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/app/data \
    ENV_FILE=/app/data/.env \
    TZ=UTC

# iputils-ping ставит /usr/bin/ping с file-capability cap_net_raw=ep,
# поэтому ICMP работает и от непривилегированного пользователя (проверено).
# Запасной путь (если capabilities запрещены) — sysctl ping_group_range в compose.
RUN apt-get update \
 && apt-get install -y --no-install-recommends iputils-ping ca-certificates tzdata \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Копируем выборочно: тесты, .env, data и логи в образ не попадают.
COPY main.py config.py ./
COPY handlers/ ./handlers/
COPY middlewares/ ./middlewares/
COPY keyboards/ ./keyboards/
COPY utils/ ./utils/

RUN useradd --create-home --uid 1000 appuser \
 && mkdir -p /app/data \
 && chown -R appuser:appuser /app
USER appuser

VOLUME ["/app/data"]

# Здоровье контейнера = способность пинговать (главный риск в Docker).
HEALTHCHECK --interval=5m --timeout=5s --start-period=20s --retries=3 \
    CMD ping -c 1 -W 1 127.0.0.1 > /dev/null || exit 1

CMD ["python", "main.py"]
