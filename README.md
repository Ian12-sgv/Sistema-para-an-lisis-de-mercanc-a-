# Unificador Consultas

Aplicacion para manejar varias consultas SQL Server y unificarlas en una sola salida operativa.

## Stack

- Backend: Python + FastAPI
- Base de datos: SQL Server
- Frontend: Electron + TypeScript + Vite
- Node: tooling del frontend y scripts del proyecto

## Estado

Esta base no intenta conectarse automaticamente a la base de datos al iniciar. La conexion queda preparada por variables de entorno porque el acceso depende de VPN.

## Configuracion

1. Copia `.env.example` a `.env`.
2. Completa `DB_NAME` y `DB_PASSWORD` en `.env`.
3. Mantén `.env` fuera de git.

Variables principales:

- `APP_ENV`: `local`, `production`, etc.
- `CORS_ORIGINS`: origenes separados por coma para el front.
- `DB_SERVER`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`: conexion SQL Server.
- `DB_CONNECTION_TIMEOUT`, `DB_QUERY_TIMEOUT`: tiempos limite de conexion y consulta.

## Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Desde la raiz del proyecto tambien puedes usar:

```powershell
.\backend\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000 --app-dir backend
```

Endpoints iniciales:

- `GET /health`
- `GET /api/queries`
- `POST /api/queries/run`
- `POST /api/queries/unify`

## Frontend

```powershell
cd frontend
npm install
npm run dev
```

## Despliegue

### DNS

Crear este registro en la zona DNS de `apipalacio.com`:

- Tipo: `A`
- Nombre/host: `apirotacion`
- Destino: `156.255.150.178`

El backend quedara disponible en `https://apirotacion.apipalacio.com`.

### Backend y Caddy

1. Ejecutar FastAPI en el servidor, escuchando solamente en `127.0.0.1:8000`.
2. Copiar [`deploy/Caddyfile`](deploy/Caddyfile) a la configuracion de Caddy.
3. Permitir los puertos TCP `80` y `443` en el firewall.
4. Recargar Caddy para que obtenga y renueve el certificado HTTPS.
5. Crear el `.env` del servidor tomando como referencia
   [`deploy/.env.production.example`](deploy/.env.production.example).

Comando recomendado para FastAPI:

```powershell
backend\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

### Frontend en Netlify

El archivo [`netlify.toml`](netlify.toml) configura:

- Directorio base: `frontend`
- Comando: `npm run build:web`
- Publicacion: `frontend/dist`
- API: `https://apirotacion.apipalacio.com`

Cuando Netlify asigne la URL final, se debe colocar esa URL exacta en
`CORS_ORIGINS` dentro del `.env` del servidor y reiniciar FastAPI.

## Tests

La guia para ejecutar y mantener las pruebas esta en [`TESTING.md`](TESTING.md).

## Consultas

Coloca las consultas iniciales en `database/consulta_base.sql` o registra nuevas definiciones en `backend/app/services/query_catalog.py`.

Cuando compartas las consultas reales, el siguiente paso sera mapear:

- Nombre de cada consulta
- Parametros
- Columnas esperadas
- Reglas para unificar resultados
- Validaciones y errores esperados
