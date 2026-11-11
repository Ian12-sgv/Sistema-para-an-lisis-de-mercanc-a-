"""SQL generado en Python para transferencias, códigos comunes y la consulta unificada."""

from datetime import date

from app.services.query_catalog import DATABASE_DIR


def build_transferencias_page_sql() -> str:
    return """
WITH FilteredMTF AS (
    SELECT
          MATRIZ
        , SUCURSAL
        , CodigoEnvia
        , CodigoRecibe
        , FechaEmision
        , FECHACARGATRANSFERENCIA
        , CodigoBarra
        , Numero
    FROM dbo.MOVTRANSFERECIAS_TIENDAS
    WHERE CodigoBarra IS NOT NULL
      AND FechaEmision >= ?
      AND FechaEmision < DATEADD(DAY, 1, ?)
      AND (? IS NULL OR CAST(CodigoBarra AS VARCHAR(50)) = CAST(? AS VARCHAR(50)))
),
NeededPairs AS (
    SELECT DISTINCT
          CodigoBarra
        , CONVERT(VARCHAR(50), Numero) AS DocumentoStr
    FROM FilteredMTF
),
LatestK AS (
    SELECT
          K.dimid_tienda
        , K.Documento
        , K.FechaMovimiento
        , K.Tipo
        , K.Concepto
        , K.Cantidad
        , K.CodigoBarra
        , ROW_NUMBER() OVER (
            PARTITION BY K.CodigoBarra, CONVERT(VARCHAR(50), K.Documento)
            ORDER BY K.FechaMovimiento DESC, K.hecid_kardex DESC
          ) AS rn
    FROM [BODEGA_DATOS].[dbo].[tbHecKardex] AS K
    INNER JOIN NeededPairs AS NP
        ON CAST(K.CodigoBarra AS VARCHAR(50)) = CAST(NP.CodigoBarra AS VARCHAR(50))
       AND CONVERT(VARCHAR(50), K.Documento) = NP.DocumentoStr
),
JoinedTransferencias AS (
    SELECT
          MTF.MATRIZ
        , MTF.SUCURSAL
        , MTF.CodigoEnvia
        , MTF.CodigoRecibe
        , MTF.FechaEmision
        , MTF.FECHACARGATRANSFERENCIA
        , MTF.CodigoBarra
        , MTF.Numero
        , HK.dimid_tienda
        , HK.Documento
        , HK.FechaMovimiento
        , HK.Tipo
        , HK.Concepto
        , HK.Cantidad
        , ROW_NUMBER() OVER (ORDER BY MTF.FechaEmision, MTF.CodigoBarra, MTF.Numero) AS page_row_number
    FROM FilteredMTF AS MTF
    LEFT JOIN LatestK AS HK
        ON CAST(HK.CodigoBarra AS VARCHAR(50)) = CAST(MTF.CodigoBarra AS VARCHAR(50))
       AND CONVERT(VARCHAR(50), HK.Documento) = CONVERT(VARCHAR(50), MTF.Numero)
       AND HK.rn = 1
    WHERE LOWER(LTRIM(RTRIM(HK.Concepto))) = 'transferencia'
)
SELECT
      MATRIZ
    , SUCURSAL
    , CodigoEnvia
    , CodigoRecibe
    , FechaEmision
    , FECHACARGATRANSFERENCIA
    , CodigoBarra
    , Numero
    , dimid_tienda
    , Documento
    , FechaMovimiento
    , Tipo
    , Concepto
    , Cantidad
FROM JoinedTransferencias
WHERE page_row_number > ?
  AND page_row_number <= ?
ORDER BY page_row_number
"""


def build_distinct_barcode_sql(sql: str) -> str:
    return (
        "SELECT DISTINCT CAST(CodigoBarra AS VARCHAR(50)) AS CodigoBarra "
        f"FROM ({sql}) AS source_query "
        "WHERE CodigoBarra IS NOT NULL"
    )


def load_unified_base_sql() -> str:
    return (DATABASE_DIR / "consulta_base_unificada.sql").read_text(encoding="utf-8")


def get_source_barcode_sql(query_id: str) -> str:
    if query_id == "consulta_base":
        return """
SELECT DISTINCT CAST(M.[CodigoBarra] AS VARCHAR(50)) AS CodigoBarra
FROM [J101010100_999911].[dbo].[COMPRAS] AS C
INNER JOIN [J101010100_999911].[dbo].[MOVCOMPRAS] AS M
    ON C.[Documento] = M.[Documento]
   AND C.[Proveedor] = M.[Proveedor]
WHERE C.IDLote <> 001
  AND C.[Fecha] >= ?
  AND C.[Fecha] < DATEADD(DAY, 1, ?)
  AND M.[CodigoBarra] IS NOT NULL
"""

    if query_id == "ventas":
        return """
SELECT DISTINCT CAST(i.CodigoBarra AS VARCHAR(50)) AS CodigoBarra
FROM dbo.tbHecInventario AS h
INNER JOIN dbo.tbDimInventario AS i
    ON i.dimID_Inventario = h.dimid_inventario
INNER JOIN dbo.tbDimTiendas AS t
    ON t.dimid_tienda = h.dimid_tienda
INNER JOIN dbo.tbHecVentas AS v
    ON v.dimid_inventario = h.dimid_inventario
   AND v.dimid_tienda = h.dimid_tienda
WHERE
    t.dimID_Tienda <> '2010'
    AND v.[FechaVenta] >= ?
    AND v.[FechaVenta] < DATEADD(DAY, 1, ?)
    AND t.Status = 1
    AND t.Tipo = 1
    AND i.CodigoBarra IS NOT NULL
"""

    if query_id == "kardex":
        return """
SELECT DISTINCT CAST(K.[CodigoBarra] AS VARCHAR(50)) AS CodigoBarra
FROM [BODEGA_DATOS].[dbo].[tbHecKardex] K
WHERE K.[FechaMovimiento] >= ?
  AND K.[FechaMovimiento] < DATEADD(DAY, 1, ?)
  AND K.[MotivoAjuste] IS NOT NULL
  AND LTRIM(RTRIM(K.[MotivoAjuste])) <> ''
  AND K.[CodigoBarra] IS NOT NULL
"""

    if query_id == "transferencias_tiendas":
        return """
WITH FilteredMTF AS (
    SELECT
          CodigoBarra
        , Numero
        , FechaEmision
    FROM dbo.MOVTRANSFERECIAS_TIENDAS
    WHERE CodigoBarra IS NOT NULL
      AND FechaEmision >= ?
      AND FechaEmision < DATEADD(DAY, 1, ?)
),
NeededPairs AS (
    SELECT DISTINCT
          CodigoBarra
        , CONVERT(VARCHAR(50), Numero) AS DocumentoStr
    FROM FilteredMTF
),
LatestK AS (
    SELECT
          K.CodigoBarra
        , K.Documento
        , K.Concepto
        , ROW_NUMBER() OVER (
            PARTITION BY K.CodigoBarra, CONVERT(VARCHAR(50), K.Documento)
            ORDER BY K.FechaMovimiento DESC, K.hecid_kardex DESC
          ) AS rn
    FROM [BODEGA_DATOS].[dbo].[tbHecKardex] AS K
    INNER JOIN NeededPairs AS NP
        ON CAST(K.CodigoBarra AS VARCHAR(50)) = CAST(NP.CodigoBarra AS VARCHAR(50))
       AND CONVERT(VARCHAR(50), K.Documento) = NP.DocumentoStr
)
SELECT DISTINCT CAST(MTF.CodigoBarra AS VARCHAR(50)) AS CodigoBarra
FROM FilteredMTF AS MTF
INNER JOIN LatestK AS HK
    ON CAST(HK.CodigoBarra AS VARCHAR(50)) = CAST(MTF.CodigoBarra AS VARCHAR(50))
   AND CONVERT(VARCHAR(50), HK.Documento) = CONVERT(VARCHAR(50), MTF.Numero)
   AND HK.rn = 1
WHERE LOWER(LTRIM(RTRIM(HK.Concepto))) = 'transferencia'
"""

    raise KeyError(f"Unsupported unified source query: {query_id}")


def get_source_barcode_parameters(query_id: str, fecha_desde: date, fecha_hasta: date) -> list:
    if query_id == "ventas":
        return [fecha_desde, fecha_hasta]
    if query_id in ("consulta_base", "kardex"):
        return [fecha_desde, fecha_hasta]
    if query_id == "transferencias_tiendas":
        return [fecha_desde, fecha_hasta]

    raise KeyError(f"Unsupported unified source query: {query_id}")


def build_unified_common_codes_sql() -> str:
    """Todos los códigos comunes del rango, ordenados. Se ejecuta una vez y se pagina en memoria."""
    return """
WITH CommonCodes AS
(
    SELECT DISTINCT
          CAST(M.CodigoBarra AS VARCHAR(50)) AS CodigoBarra
FROM [J101010100_999911].[dbo].[COMPRAS] AS C
INNER JOIN [J101010100_999911].[dbo].[MOVCOMPRAS] AS M
    ON C.Documento = M.Documento
   AND C.Proveedor = M.Proveedor
WHERE C.IDLote <> 001
  AND C.Fecha >= ?
  AND C.Fecha < DATEADD(DAY, 1, ?)
  AND M.CodigoBarra IS NOT NULL
  AND EXISTS
  (
      SELECT 1
      FROM dbo.tbHecVentas AS V
      INNER JOIN dbo.tbHecInventario AS H
          ON V.dimid_inventario = H.dimid_inventario
         AND V.dimid_tienda = H.dimid_tienda
      INNER JOIN dbo.tbDimInventario AS I
          ON I.dimID_Inventario = H.dimid_inventario
      INNER JOIN dbo.tbDimTiendas AS T
          ON T.dimid_tienda = H.dimid_tienda
      WHERE V.FechaVenta >= ?
        AND V.FechaVenta < DATEADD(DAY, 1, ?)
        AND T.dimID_Tienda <> '2010'
        AND T.Status = 1
        AND T.Tipo = 1
        AND CAST(I.CodigoBarra AS VARCHAR(50)) = CAST(M.CodigoBarra AS VARCHAR(50))
  )
  AND EXISTS
  (
      SELECT 1
      FROM [BODEGA_DATOS].[dbo].[tbHecKardex] AS K
      WHERE K.FechaMovimiento >= ?
        AND K.FechaMovimiento < DATEADD(DAY, 1, ?)
        AND K.MotivoAjuste IS NOT NULL
        AND LTRIM(RTRIM(K.MotivoAjuste)) <> ''
        AND CAST(K.CodigoBarra AS VARCHAR(50)) = CAST(M.CodigoBarra AS VARCHAR(50))
  )
  AND EXISTS
  (
      SELECT 1
      FROM dbo.MOVTRANSFERECIAS_TIENDAS AS MTF
      WHERE MTF.CodigoBarra IS NOT NULL
        AND MTF.FechaEmision >= ?
        AND MTF.FechaEmision < DATEADD(DAY, 1, ?)
        AND CAST(MTF.CodigoBarra AS VARCHAR(50)) = CAST(M.CodigoBarra AS VARCHAR(50))
        AND EXISTS
        (
            SELECT 1
            FROM [BODEGA_DATOS].[dbo].[tbHecKardex] AS K2
            WHERE CAST(K2.CodigoBarra AS VARCHAR(50)) = CAST(MTF.CodigoBarra AS VARCHAR(50))
              AND CONVERT(VARCHAR(50), K2.Documento) = CONVERT(VARCHAR(50), MTF.Numero)
              AND LOWER(LTRIM(RTRIM(K2.Concepto))) = 'transferencia'
        )
  )
)
SELECT CodigoBarra
FROM CommonCodes
ORDER BY CodigoBarra
"""


def build_unified_base_only_detail_sql(base_sql: str, code_count: int) -> str:
    placeholders = ", ".join(["?"] * code_count)

    return f"""
SELECT
      CAST(CodigoBarra AS VARCHAR(50)) AS [Codigo Barra]
    , Referencia AS [Referencias]
    , CodigoMarca AS [Codigo Marca]
    , marca_detail.NombreMarca AS [Marca]
    , Nombre AS [Descripcion]
    , marca_detail.NombreMarca AS [Nombre Marca]
    , Fabricante AS [Codigo Fabricante]
    , NombreFabricante AS [Nombre Fabricante]
    , CodigoCategoria AS [Codigo Categoria]
    , NombreCategoria AS [Nombre Categoria]
    , CodigoLinea AS [Codigo Linea]
    , NombreLinea AS [Nombre Linea]
    , Usuario AS [Usuarios]
    , Documento AS [Numero de compra]
    , FechaFactura AS [Fecha Factura]
    , Observacion AS [Descripcion de compra]
    , CantidadDevuelta AS [Correcciones de compra]
    , Cantidad AS [Cantidad de compra]
    , [Suma Unidades Compra] AS [Suma Unidades Compras]
FROM ({base_sql}) AS base_query
OUTER APPLY
(
    SELECT TOP 1
          MC.[Nombre] AS NombreMarca
    FROM [J101010100_999911].[dbo].[MARCAS] AS MC
    WHERE CAST(MC.[Codigo] AS VARCHAR(50)) = CAST(base_query.CodigoMarca AS VARCHAR(50))
) AS marca_detail
WHERE CAST(CodigoBarra AS VARCHAR(50)) IN ({placeholders})
ORDER BY CodigoBarra
"""


def build_unified_base_detail_sql(base_sql: str, code_count: int | None) -> str:
    top_clause = "TOP (?) " if code_count is None else ""
    code_filter = ""

    if code_count is not None:
        placeholders = ", ".join(["?"] * code_count)
        code_filter = f"WHERE CAST(CodigoBarra AS VARCHAR(50)) IN ({placeholders})"

    unified_base_sql = base_sql

    return f"""
SELECT {top_clause}
      CAST(CodigoBarra AS VARCHAR(50)) AS [Codigo Barra]
    , Referencia AS [Referencias]
    , CodigoMarca AS [Codigo Marca]
    , marca_detail.NombreMarca AS [Marca]
    , Nombre AS [Descripcion]
    , marca_detail.NombreMarca AS [Nombre Marca]
    , Fabricante AS [Codigo Fabricante]
    , NombreFabricante AS [Nombre Fabricante]
    , CodigoCategoria AS [Codigo Categoria]
    , NombreCategoria AS [Nombre Categoria]
    , CodigoLinea AS [Codigo Linea]
    , NombreLinea AS [Nombre Linea]
    , Usuario AS [Usuarios]
    , Documento AS [Numero de compra]
    , FechaFactura AS [Fecha Factura]
    , Observacion AS [Descripcion de compra]
    , CantidadDevuelta AS [Correcciones de compra]
    , Cantidad AS [Cantidad de compra]
    , [Suma Unidades Compra] AS [Suma Unidades Compras]
    , sales_detail.ExistenciaActual AS [Existencia actual]
    , sales_detail.SumaExistencia AS [Suma Existencia]
    , CASE
        WHEN sales_detail.ExistenciaActual IS NULL OR sales_detail.ExistenciaActual = 0 THEN NULL
        ELSE (CAST(Cantidad AS FLOAT) / NULLIF(CAST(sales_detail.ExistenciaActual AS FLOAT), 0)) * 100
      END AS [Porcentaje de existencia%]
    , sales_detail.UnidadesVendidas AS [Unidades vendidas]
    , sales_detail.UnidadesVendidas AS [Suma Cantidades ventas]
    , CASE
        WHEN sales_detail.UnidadesVendidas IS NULL OR sales_detail.UnidadesVendidas = 0 THEN NULL
        ELSE (CAST(Cantidad AS FLOAT) / NULLIF(CAST(sales_detail.UnidadesVendidas AS FLOAT), 0)) * 100
      END AS [porcentaje de unidades vendidas%]
    , sales_detail.NumeroFactura
    , sales_detail.FechaVenta
    , sales_detail.Tienda
    , sales_detail.Region
    , sales_detail.PrecioDetal
    , sales_detail.CostoDolar
    , sales_detail.PrecioMayor
    , sales_detail.PrecioPromocion
    , kardex_detail.CostoInicial * ISNULL(sales_detail.UnidadesVendidas, 0) AS [Utilidad por ventas]
    , CASE
        WHEN (kardex_detail.CostoInicial * ISNULL(sales_detail.UnidadesVendidas, 0)) = 0 THEN NULL
        ELSE (CAST(Cantidad AS FLOAT) / NULLIF(CAST(kardex_detail.CostoInicial * ISNULL(sales_detail.UnidadesVendidas, 0) AS FLOAT), 0)) * 100
      END AS [% Utilidad por ventas]
    , kardex_detail.CostoInicial AS [Costo Inicial]
    , kardex_detail.NombreTienda AS [Kardex Nombre Tienda]
    , kardex_detail.hecid_kardex AS [Kardex hecid]
    , kardex_detail.dimid_fechamovimiento AS [Kardex dimid fecha movimiento]
    , kardex_detail.NombreArticulo AS [Kardex Nombre Articulo]
    , kardex_detail.Tipo AS [Kardex Tipo]
    , kardex_detail.Concepto AS [Kardex Concepto]
    , kardex_detail.MotivoAjuste AS [Kardex Motivo Ajuste]
    , kardex_detail.FechaMovimiento AS [Kardex Fecha Movimiento]
    , kardex_detail.Documento AS [Kardex Documento]
    , kardex_detail.Observacion AS [Kardex Observacion]
    , kardex_detail.Item AS [Kardex Item]
    , kardex_detail.Referencia AS [Kardex Referencia]
    , kardex_detail.CodigoMarca AS [Kardex Codigo Marca]
    , kardex_detail.Cantidad AS [Kardex Cantidad]
    , kardex_detail.Existencia AS [Kardex Existencia]
    , kardex_detail.CantidadRM AS [Kardex Cantidad RM]
    , kardex_detail.ExistenciaRM AS [Kardex Existencia RM]
    , kardex_detail.AjustesPositivos AS [Unidades de Ajustes Positivos]
    , CASE
        WHEN kardex_detail.AjustesPositivos IS NULL OR kardex_detail.AjustesPositivos = 0 THEN NULL
        ELSE (CAST(Cantidad AS FLOAT) / NULLIF(CAST(kardex_detail.AjustesPositivos AS FLOAT), 0)) * 100
      END AS [% Ajustes Positivos]
    , kardex_detail.AjustesNegativos AS [Unidades de Ajustes Negativos]
    , CASE
        WHEN kardex_detail.AjustesNegativos IS NULL OR kardex_detail.AjustesNegativos = 0 THEN NULL
        ELSE (CAST(Cantidad AS FLOAT) / NULLIF(CAST(kardex_detail.AjustesNegativos AS FLOAT), 0)) * 100
      END AS [% Ajustes Negativos]
    , kardex_detail.CostoInicial * ISNULL(kardex_detail.AjustesNegativos, 0) AS [Utilidad perdida por ajustes]
    , CASE
        WHEN (kardex_detail.CostoInicial * ISNULL(kardex_detail.AjustesNegativos, 0)) = 0 THEN NULL
        ELSE (CAST(Cantidad AS FLOAT) / NULLIF(CAST(kardex_detail.CostoInicial * ISNULL(kardex_detail.AjustesNegativos, 0) AS FLOAT), 0)) * 100
      END AS [% Utilidad perdida por ajustes]
    , transfer_detail.MATRIZ AS [Transferencia matriz]
    , transfer_detail.SUCURSAL AS [Transferencia sucursal]
    , transfer_detail.CodigoEnvia AS [Codigo envia]
    , transfer_detail.CodigoRecibe AS [Codigo recibe]
    , transfer_detail.FechaEmision AS [Fecha emision transferencia]
    , transfer_detail.FECHACARGATRANSFERENCIA AS [Fecha carga transferencia]
    , transfer_detail.Numero AS [Numero transferencia]
    , transfer_detail.dimid_tienda AS [Tienda kardex transferencia]
FROM ({unified_base_sql}) AS base_query
OUTER APPLY
(
    SELECT TOP 1
          MC.[Nombre] AS NombreMarca
    FROM [J101010100_999911].[dbo].[MARCAS] AS MC
    WHERE CAST(MC.[Codigo] AS VARCHAR(50)) = CAST(base_query.CodigoMarca AS VARCHAR(50))
) AS marca_detail
CROSS APPLY
(
    SELECT
          MAX(T.Nombre) AS NombreTienda
        , MAX(K.[hecid_kardex]) AS hecid_kardex
        , MAX(K.[dimid_fechamovimiento]) AS dimid_fechamovimiento
        , MAX(H.[Nombre]) AS NombreArticulo
        , MAX(K.[Tipo]) AS Tipo
        , MAX(K.[Concepto]) AS Concepto
        , MAX(K.[MotivoAjuste]) AS MotivoAjuste
        , MAX(K.[FechaMovimiento]) AS FechaMovimiento
        , MAX(K.[Documento]) AS Documento
        , MAX(K.[Observacion]) AS Observacion
        , MAX(K.[Item]) AS Item
        , MAX(K.[Referencia]) AS Referencia
        , MAX(K.[CodigoMarca]) AS CodigoMarca
        , SUM(ISNULL(K.[Cantidad], 0)) AS Cantidad
        , MAX(I.[CostoInicial]) AS CostoInicial
        , MAX(K.[Existencia]) AS Existencia
        , SUM(ISNULL(K.[CantidadRM], 0)) AS CantidadRM
        , MAX(K.[ExistenciaRM]) AS ExistenciaRM
        , SUM(CASE WHEN LOWER(LTRIM(RTRIM(K.[Tipo]))) = 'entrada' THEN ISNULL(K.[Cantidad], 0) ELSE 0 END) AS AjustesPositivos
        , SUM(CASE WHEN LOWER(LTRIM(RTRIM(K.[Tipo]))) = 'salida' THEN ABS(ISNULL(K.[Cantidad], 0)) ELSE 0 END) AS AjustesNegativos
    FROM [BODEGA_DATOS].[dbo].[tbHecKardex] K
    INNER JOIN [BODEGA_DATOS].[dbo].[tbDimTiendas] T
        ON K.[dimid_tienda] = T.[dimid_tienda]
    INNER JOIN [BODEGA_DATOS].[dbo].[tbHecInventario] I
        ON K.[dimid_inventario] = I.[dimid_inventario]
    INNER JOIN [BODEGA_DATOS].[dbo].[tbDimInventario] H
        ON H.[dimid_inventario] = I.[dimid_inventario]
    WHERE K.[FechaMovimiento] >= ?
      AND K.[FechaMovimiento] < DATEADD(DAY, 1, ?)
      AND K.[MotivoAjuste] IS NOT NULL
      AND LTRIM(RTRIM(K.[MotivoAjuste])) <> ''
      AND CAST(K.[CodigoBarra] AS VARCHAR(50)) = CAST(base_query.CodigoBarra AS VARCHAR(50))
    HAVING COUNT_BIG(*) > 0
) AS kardex_detail
CROSS APPLY
(
    SELECT
          MAX(CASE WHEN h.[Existencia] < 0 THEN 0 ELSE h.[Existencia] END) AS ExistenciaActual
        , SUM(CASE WHEN h.[Existencia] < 0 THEN 0 ELSE h.[Existencia] END) AS SumaExistencia
        , SUM(ISNULL(v.[Cantidad], 0)) AS UnidadesVendidas
        , MAX(v.[NumeroFactura]) AS NumeroFactura
        , MAX(v.[FechaVenta]) AS FechaVenta
        , MAX(t.[Nombre]) AS Tienda
        , MAX(t.[Zona]) AS Region
        , MAX(CAST(ROUND(c.[PrecioDetal], 2) AS DECIMAL(18,2))) AS PrecioDetal
        , MAX(CAST(ROUND(c.[CostoInicial], 2) AS DECIMAL(18,2))) AS CostoDolar
        , MAX(CAST(ROUND(c.[PrecioMayor], 2) AS DECIMAL(18,2))) AS PrecioMayor
        , MAX(CAST(ROUND(c.[PrecioPromocion], 2) AS DECIMAL(18,2))) AS PrecioPromocion
    FROM dbo.tbHecInventario AS h
    INNER JOIN dbo.tbDimInventario AS i
        ON i.dimID_Inventario = h.dimid_inventario
    INNER JOIN dbo.tbDimTiendas AS t
        ON t.dimid_tienda = h.dimid_tienda
    INNER JOIN [J101010100_999911].[dbo].[Inventario] AS c
        ON c.CodigoBarra = i.CodigoBarra
    INNER JOIN dbo.tbHecVentas AS v
        ON v.dimid_inventario = h.dimid_inventario
       AND v.dimid_tienda = h.dimid_tienda
    WHERE v.[FechaVenta] >= ?
      AND v.[FechaVenta] < DATEADD(DAY, 1, ?)
      AND t.dimID_Tienda <> '2010'
      AND t.Status = 1
      AND t.Tipo = 1
      AND CAST(i.CodigoBarra AS VARCHAR(50)) = CAST(base_query.CodigoBarra AS VARCHAR(50))
    HAVING COUNT_BIG(*) > 0
) AS sales_detail
CROSS APPLY
(
    SELECT TOP 1
          MTF.MATRIZ
        , MTF.SUCURSAL
        , MTF.CodigoEnvia
        , MTF.CodigoRecibe
        , MTF.FechaEmision
        , MTF.FECHACARGATRANSFERENCIA
        , MTF.Numero
        , HK.dimid_tienda
    FROM dbo.MOVTRANSFERECIAS_TIENDAS AS MTF
    CROSS APPLY
    (
        SELECT TOP 1
              K.dimid_tienda
            , K.Concepto
        FROM [BODEGA_DATOS].[dbo].[tbHecKardex] AS K
        WHERE CAST(K.CodigoBarra AS VARCHAR(50)) = CAST(MTF.CodigoBarra AS VARCHAR(50))
          AND CONVERT(VARCHAR(50), K.Documento) = CONVERT(VARCHAR(50), MTF.Numero)
        ORDER BY K.FechaMovimiento DESC, K.hecid_kardex DESC
    ) AS HK
    WHERE MTF.CodigoBarra IS NOT NULL
      AND MTF.FechaEmision >= ?
      AND MTF.FechaEmision < DATEADD(DAY, 1, ?)
      AND CAST(MTF.CodigoBarra AS VARCHAR(50)) = CAST(base_query.CodigoBarra AS VARCHAR(50))
      AND LOWER(LTRIM(RTRIM(HK.Concepto))) = 'transferencia'
    ORDER BY MTF.FechaEmision DESC, MTF.Numero DESC
) AS transfer_detail
{code_filter}
ORDER BY CodigoBarra
"""


def build_kardex_detail_raw_sql() -> str:
    return """
SELECT
      K.[CodigoBarra] AS CodigoBarra
    , K.[Tipo]
    , K.[Cantidad]
    , I.[CostoInicial]
FROM [BODEGA_DATOS].[dbo].[tbHecKardex] K
INNER JOIN [BODEGA_DATOS].[dbo].[tbHecInventario] I
    ON K.[dimid_inventario] = I.[dimid_inventario]
WHERE K.[FechaMovimiento] >= ?
  AND K.[MotivoAjuste] IS NOT NULL
  AND LTRIM(RTRIM(K.[MotivoAjuste])) <> ''
  AND (
        ? IS NULL
        OR CAST(K.[CodigoBarra] AS VARCHAR(50)) IN (
            SELECT LTRIM(RTRIM([value]))
            FROM STRING_SPLIT(CAST(? AS VARCHAR(MAX)), ',')
        )
      )
"""
