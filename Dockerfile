# Imagen del backend (FastAPI + ODBC Driver 17 para SQL Server).
# El frontend se publica aparte (Netlify).
#
# Construir:  docker build -t sistemaspdb/rotacion .
# Ejecutar:   docker run -p 8000:8000 --env-file .env -v unificador-cache:/app/.cache sistemaspdb/rotacion

# bookworm (Debian 12): Microsoft publica msodbcsql17 para esta versión.
FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl gnupg ca-certificates \
    && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
        | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
    && echo "deb [arch=amd64,arm64 signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" \
        > /etc/apt/sources.list.d/microsoft-prod.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql17 unixodbc \
    && apt-get purge -y --auto-remove curl gnupg \
    && rm -rf /var/lib/apt/lists/*

# El código calcula rutas desde la raíz del repo (backend/app, database/, .cache/),
# así que la imagen conserva esa misma estructura bajo /app.
WORKDIR /app

COPY backend/pyproject.toml backend/pyproject.toml
COPY backend/app backend/app
RUN pip install -e ./backend

COPY database database

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/.cache \
    && chown -R appuser:appuser /app/.cache
USER appuser

# Snapshots Parquet/DuckDB: montar un volumen para conservarlos entre reinicios.
VOLUME ["/app/.cache"]

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"

# La configuración (DB_*, CORS_ORIGINS, APP_ENV...) se pasa como variables de entorno.
CMD ["uvicorn", "app.main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000"]
