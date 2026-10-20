FROM python:3.12-slim-bookworm

ARG BUILD_VERSION=dev

ENV TZ=Europe/Amsterdam \
    ADDON_VERSION=${BUILD_VERSION} \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && pip install --no-cache-dir playwright==1.48.0 websocket-client==1.8.0 tzdata \
    && playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

COPY app /app
WORKDIR /app
CMD ["python3", "/app/server.py"]
