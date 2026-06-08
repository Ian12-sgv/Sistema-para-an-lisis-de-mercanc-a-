# Testing

Estas pruebas validan la logica del backend y frontend sin depender de la VPN ni de SQL Server. Las consultas a base de datos se prueban con mocks o snapshots locales.

## Backend

Instala dependencias del backend:

```powershell
backend\.venv\Scripts\python.exe -m pip install -e backend
```

Ejecuta los tests:

```powershell
backend\.venv\Scripts\python.exe -m pytest backend\tests
```

Cobertura principal:

- `build_ordered_parameters` para `ventas`, `kardex` y `transferencias_tiendas`.
- Interseccion estricta de codigos comunes para `consulta_unificada`.
- Persistencia de codigos comunes en cache/snapshot.
- Filtros globales sobre snapshots Parquet con DuckDB.
- Paginacion filtrada.
- SQL de transferencias con comparacion segura de `Documento`/`Numero` y `Concepto`.

Resultado esperado actual:

```text
17 passed
```

## Frontend

Instala dependencias del frontend:

```powershell
npm.cmd --prefix frontend install
```

Ejecuta los tests:

```powershell
npm.cmd --prefix frontend test
```

Ejecuta typecheck:

```powershell
npm.cmd --prefix frontend run typecheck
```

Cobertura principal:

- `runQuery` envia `queryId`, `parameters`, `page` y `pageSize`.
- `consulta_unificada` envia filtros globales al backend.
- Los filtros de tabla de la unificada no se aplican solo a la pagina visible.
- Los filtros locales de entrada/salida positiva/negativa siguen funcionando.

Resultado esperado actual:

```text
8 passed
```

## Nota operativa

Si un codigo de barra existe en SQL Server pero no aparece en `consulta_unificada`, usa primero los tests y luego valida estos puntos en SQL Server:

- Existe en `consulta_base`.
- Existe en `ventas` con `t.Status = 1`, `t.Tipo = 1` y `t.dimID_Tienda <> '2010'`.
- Existe en `kardex` con `MotivoAjuste` no nulo ni vacio.
- Existe en `transferencias_tiendas` con `Concepto` normalizado como `transferencia`.
- El rango de fecha aplica correctamente para cada fuente.
