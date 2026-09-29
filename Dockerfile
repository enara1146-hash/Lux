# Railway production image for Lux
FROM python:3.12-slim AS lux_runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    LUX_DATA_DIR=/data

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git \
        curl \
        ca-certificates \
        nodejs \
        npm \
        openjdk-17-jre-headless \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the complete repository so the Docker build does not depend on
# individual directories being present in a partial build context.
COPY . /app/

RUN python -m pip install --upgrade pip \
    && pip install .

RUN mkdir -p /data/projects /data/jobs /data/state

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://127.0.0.1:${PORT:-8080}/health || exit 1

CMD ["sh", "-c", "exec uvicorn lux.server.app:app --host 0.0.0.0 --port ${PORT:-8080}"]
