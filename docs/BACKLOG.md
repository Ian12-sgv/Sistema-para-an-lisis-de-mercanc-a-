# Backlog

Ultima revision: 2026-11-11 (estado verificado contra el codigo).

| Priority | Area | Task | Acceptance Criteria | Status |
|---|---|---|---|---|
| P0 | Backend | Registrar consultas reales | Cada consulta tiene id, nombre, descripcion y archivo SQL | Done — 5 consultas en `query_catalog.py` |
| P0 | Backend | Definir parametros por consulta | La API valida parametros antes de ejecutar SQL | Done — `build_ordered_parameters` responde 400 si faltan |
| P0 | Backend | Unificar resultados | Varias consultas producen una tabla comun con origen identificado | Done — `consulta_unificada` y `POST /api/queries/unify` |
| P0 | Frontend | Ejecutar consultas desde Electron | El usuario selecciona consultas y ve resultados | Done — web (Netlify) y Electron |
| P1 | Frontend | Filtros y parametros | La UI permite capturar fechas, codigos u otros filtros | Done — fechas, codigo de barra, filtros de tabla y de ajustes |
| P1 | Exportacion | Exportar resultados | El usuario descarga CSV o Excel | Done — botones CSV y Excel en `App.tsx` |
| P1 | Rendimiento | Cache de consultas pesadas | Paginas siguientes y consultas repetidas no vuelven a SQL Server | Done — snapshots Parquet/DuckDB y prefetch |
| P1 | Frontend | Dashboard | Metricas y graficas por fuente, categoria y marca | Done — `POST /api/queries/dashboard` |
| P1 | Seguridad | Manejo seguro de credenciales | Secretos viven solo en `.env` local | In progress — `.env` fuera de git; falta quitar los valores por defecto de servidor/usuario en `core/config.py` y usar un usuario de solo lectura en lugar de `sa` |
| P1 | Seguridad | Autenticacion de la API | Solo usuarios autorizados pueden consultar la API publica | Pending |
| P2 | Auditoria | Historial de ejecuciones | Se conserva fecha, consulta y estado de ejecucion | Pending |
| P2 | Operacion | Limpieza de cache | `.cache/` no crece sin limite | Pending |
| P2 | Mantenimiento | Dividir `query_runner.py` | Ningun modulo mezcla todas las fuentes | Done — paquete `services/query_runner/` |
