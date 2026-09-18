FROM python:3.12-slim
ARG APP_VERSION=0.1.0-preview.2
ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG NO_PROXY
LABEL org.opencontainers.image.title="Maintune" \
      org.opencontainers.image.version="$APP_VERSION" \
      org.opencontainers.image.licenses="AGPL-3.0-only" \
      org.opencontainers.image.source="https://github.com/mcxianyujun/maintune" \
      io.ai-maintainer.install-mode="local-build"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 OH_PERSISTENCE_DIR=/app/data/openhands OPENHANDS_SUPPRESS_BANNER=1
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir --disable-pip-version-check -r requirements.lock \
    && pip check \
    && python -c "import openhands.sdk; print('OpenHands SDK import: OK')" \
    && useradd --uid 10001 --create-home maintainer
COPY pyproject.toml ./
COPY backend ./backend
RUN pip install --no-cache-dir --no-deps .
RUN pip check
COPY --chown=maintainer:maintainer frontend/dist ./frontend/dist
RUN chmod -R a+rX /app/frontend/dist
RUN mkdir -p /app/data && chown maintainer:maintainer /app/data
USER maintainer
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=3)"
CMD ["uvicorn", "maintainer.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
