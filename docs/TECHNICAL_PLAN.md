# Technical Plan

## Objetivo

Preparar una aplicacion de escritorio para manejar varias consultas SQL Server y unificarlas en una salida comun.

## Arquitectura

- `backend/`: API FastAPI.
- `frontend/`: Electron + React + TypeScript.
- `database/`: archivos `.sql` versionables.
- `shared/`: contratos compartidos para TypeScript.

## Base De Datos

Motor: SQL Server.

Conexion esperada:

- Servidor: `SERVERDOS\SERVERSQL_DOS`
- Usuario: `sa`
- Autenticacion: SQL Server
- Cifrado: obligatorio
- Certificado de servidor de confianza: activado

La clave no debe quedar hardcodeada en el codigo. Configurarla localmente en `.env`.

## Backend

FastAPI expone:

- `GET /health`
- `GET /api/queries`
- `POST /api/queries/run`
- `POST /api/queries/unify`

La ejecucion SQL esta aislada en `app/db/sql_server.py`.

## Frontend

Electron carga una UI Vite/React para:

- Listar consultas disponibles.
- Seleccionar una o varias consultas.
- Ejecutar una consulta individual.
- Unificar resultados.
- Mostrar tabla de salida.

## Decision: Prisma

No se incluye Prisma en la version inicial porque el flujo principal es ejecutar consultas SQL existentes, no modelar CRUD relacional desde cero.

Prisma podria agregarse luego si aparecen necesidades como:

- CRUD de configuracion de consultas.
- Usuarios, roles y auditoria.
- Persistencia de historiales.
- Modelos relacionales mantenidos por migraciones.

## Siguiente Paso

Cuando esten las consultas reales:

1. Crear un archivo `.sql` por consulta en `database/`.
2. Registrar cada consulta en `backend/app/services/query_catalog.py`.
3. Definir parametros requeridos.
4. Acordar reglas de unificacion.
5. Agregar validaciones y pruebas.

