"""SQL generado en Python para transferencias, códigos comunes y la consulta unificada."""

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


# Regla de la consulta unificada: un codigo entra si en el rango de fechas
#   1) se compro (COMPRAS/MOVCOMPRAS, sin el lote 001),
#   2) tuvo ajustes de kardex (MotivoAjuste informado),
#   3) tuvo ventas en tiendas activas (sin la 2010) y
#   4) tuvo una transferencia cuyo ultimo movimiento en kardex es de concepto 'transferencia'.
#
# Cada paso se guarda en una tabla temporal y solo trabaja con los codigos que pasaron el
# anterior. Asi kardex se lee una vez en lugar de una vez por cada linea o transferencia.
UNIFIED_RULE_STEPS_SQL = """
SET NOCOUNT ON;

DECLARE @FechaDesde DATE = ?;
DECLARE @FechaHasta DATE = ?;
DECLARE @FechaFin DATE = DATEADD(DAY, 1, @FechaHasta);

DROP TABLE IF EXISTS #u_compras, #u_sales, #u_mtf, #u_kdoc, #u_transfer, #u_kardex, #u_existencia;

/* 1) Codigos comprados en el rango */
SELECT DISTINCT CAST(M.[CodigoBarra] AS VARCHAR(50)) AS CodigoBarra
INTO #u_compras
FROM [J101010100_999911].[dbo].[COMPRAS] AS C
INNER JOIN [J101010100_999911].[dbo].[MOVCOMPRAS] AS M
    ON C.[Documento] = M.[Documento]
   AND C.[Proveedor] = M.[Proveedor]
WHERE C.IDLote <> 001
  AND C.[Fecha] >= @FechaDesde
  AND C.[Fecha] < @FechaFin
  AND M.[CodigoBarra] IS NOT NULL;

CREATE UNIQUE CLUSTERED INDEX IX_u_compras ON #u_compras (CodigoBarra);

/* 2) Ajustes de kardex del rango (obligatorios): una fila por codigo comprado */
SELECT
      CAST(K.[CodigoBarra] AS VARCHAR(50)) AS CodigoBarra
    , MAX(T.Nombre) AS NombreTienda
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
INTO #u_kardex
FROM [BODEGA_DATOS].[dbo].[tbHecKardex] K
INNER JOIN [BODEGA_DATOS].[dbo].[tbDimTiendas] T
    ON K.[dimid_tienda] = T.[dimid_tienda]
INNER JOIN [BODEGA_DATOS].[dbo].[tbHecInventario] I
    ON K.[dimid_inventario] = I.[dimid_inventario]
INNER JOIN [BODEGA_DATOS].[dbo].[tbDimInventario] H
    ON H.[dimid_inventario] = I.[dimid_inventario]
WHERE K.[FechaMovimiento] >= @FechaDesde
  AND K.[FechaMovimiento] < @FechaFin
  AND K.[MotivoAjuste] IS NOT NULL
  AND LTRIM(RTRIM(K.[MotivoAjuste])) <> ''
  AND K.[CodigoBarra] IS NOT NULL
  AND EXISTS (SELECT 1 FROM #u_compras uc WHERE uc.CodigoBarra = CAST(K.[CodigoBarra] AS VARCHAR(50)))
GROUP BY CAST(K.[CodigoBarra] AS VARCHAR(50));

CREATE UNIQUE CLUSTERED INDEX IX_u_kardex ON #u_kardex (CodigoBarra);

/* 3) Ventas del rango: una fila por codigo comprado y ajustado */
SELECT
      CAST(i.CodigoBarra AS VARCHAR(50)) AS CodigoBarra
    , SUM(ISNULL(v.[Cantidad], 0)) AS UnidadesVendidas
    , MAX(v.[NumeroFactura]) AS NumeroFactura
    , MAX(v.[FechaVenta]) AS FechaVenta
    , MAX(t.[Nombre]) AS Tienda
    , MAX(t.[Zona]) AS Region
    , MAX(CAST(ROUND(c.[PrecioDetal], 2) AS DECIMAL(18,2))) AS PrecioDetal
    , MAX(CAST(ROUND(c.[CostoInicial], 2) AS DECIMAL(18,2))) AS CostoDolar
    , MAX(CAST(ROUND(c.[PrecioMayor], 2) AS DECIMAL(18,2))) AS PrecioMayor
    , MAX(CAST(ROUND(c.[PrecioPromocion], 2) AS DECIMAL(18,2))) AS PrecioPromocion
INTO #u_sales
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
WHERE v.[FechaVenta] >= @FechaDesde
  AND v.[FechaVenta] < @FechaFin
  AND t.dimID_Tienda <> '2010'
  AND t.Status = 1
  AND t.Tipo = 1
  AND EXISTS (SELECT 1 FROM #u_kardex uk WHERE uk.CodigoBarra = CAST(i.CodigoBarra AS VARCHAR(50)))
GROUP BY CAST(i.CodigoBarra AS VARCHAR(50));

CREATE UNIQUE CLUSTERED INDEX IX_u_sales ON #u_sales (CodigoBarra);

/* 4a) Transferencias del rango de codigos comprados, ajustados y vendidos */
SELECT
      CAST(MTF.CodigoBarra AS VARCHAR(50)) AS CodigoBarra
    , CONVERT(VARCHAR(50), MTF.Numero) AS NumeroTexto
    , MTF.MATRIZ
    , MTF.SUCURSAL
    , MTF.CodigoEnvia
    , MTF.CodigoRecibe
    , MTF.FechaEmision
    , MTF.FECHACARGATRANSFERENCIA
    , MTF.Numero
INTO #u_mtf
FROM dbo.MOVTRANSFERECIAS_TIENDAS AS MTF
WHERE MTF.CodigoBarra IS NOT NULL
  AND MTF.FechaEmision >= @FechaDesde
  AND MTF.FechaEmision < @FechaFin
  AND EXISTS (SELECT 1 FROM #u_sales us WHERE us.CodigoBarra = CAST(MTF.CodigoBarra AS VARCHAR(50)));

CREATE CLUSTERED INDEX IX_u_mtf ON #u_mtf (CodigoBarra, NumeroTexto);

/* 4b) Ultimo movimiento de kardex por codigo + documento (kardex se lee una sola vez) */
SELECT y.CodigoBarra, y.Documento, y.dimid_tienda, y.Concepto
INTO #u_kdoc
FROM
(
    SELECT
          CAST(K.CodigoBarra AS VARCHAR(50)) AS CodigoBarra
        , CONVERT(VARCHAR(50), K.Documento) AS Documento
        , K.dimid_tienda
        , K.Concepto
        , ROW_NUMBER() OVER (
            PARTITION BY CAST(K.CodigoBarra AS VARCHAR(50)), CONVERT(VARCHAR(50), K.Documento)
            ORDER BY K.FechaMovimiento DESC, K.hecid_kardex DESC
          ) AS rn
    FROM [BODEGA_DATOS].[dbo].[tbHecKardex] AS K
    WHERE EXISTS
    (
        SELECT 1
        FROM #u_mtf um
        WHERE um.CodigoBarra = CAST(K.CodigoBarra AS VARCHAR(50))
          AND um.NumeroTexto = CONVERT(VARCHAR(50), K.Documento)
    )
) AS y
WHERE y.rn = 1;

CREATE UNIQUE CLUSTERED INDEX IX_u_kdoc ON #u_kdoc (CodigoBarra, Documento);

/* 4c) Ultima transferencia por codigo cuyo ultimo movimiento en kardex es 'transferencia' */
SELECT
      x.CodigoBarra, x.MATRIZ, x.SUCURSAL, x.CodigoEnvia, x.CodigoRecibe
    , x.FechaEmision, x.FECHACARGATRANSFERENCIA, x.Numero, x.dimid_tienda
INTO #u_transfer
FROM
(
    SELECT
          um.CodigoBarra
        , um.MATRIZ
        , um.SUCURSAL
        , um.CodigoEnvia
        , um.CodigoRecibe
        , um.FechaEmision
        , um.FECHACARGATRANSFERENCIA
        , um.Numero
        , kd.dimid_tienda
        , ROW_NUMBER() OVER (
            PARTITION BY um.CodigoBarra
            ORDER BY um.FechaEmision DESC, um.Numero DESC
          ) AS rn
    FROM #u_mtf AS um
    INNER JOIN #u_kdoc AS kd
        ON kd.CodigoBarra = um.CodigoBarra
       AND kd.Documento = um.NumeroTexto
    WHERE LOWER(LTRIM(RTRIM(kd.Concepto))) = 'transferencia'
) AS x
WHERE x.rn = 1;

CREATE UNIQUE CLUSTERED INDEX IX_u_transfer ON #u_transfer (CodigoBarra);
"""


# Existencia actual sumando cada tienda y bodega activa una sola vez (los negativos cuentan como 0).
EXISTENCIA_POR_TIENDA_FROM_SQL = """
FROM dbo.tbHecInventario AS h
INNER JOIN dbo.tbDimInventario AS i
    ON i.dimID_Inventario = h.dimid_inventario
INNER JOIN [BODEGA_DATOS].[dbo].[tbDimTiendas] AS t
    ON t.dimid_tienda = h.dimid_tienda
WHERE t.Status = 1"""

UNIFIED_EXISTENCIA_STEP_SQL = (
    """
/* 5) Existencia total por codigo en todas las tiendas y bodegas activas */
SELECT
      CAST(i.CodigoBarra AS VARCHAR(50)) AS CodigoBarra
    , SUM(CASE WHEN h.[Existencia] < 0 THEN 0 ELSE ISNULL(h.[Existencia], 0) END) AS ExistenciaTotal
INTO #u_existencia"""
    + EXISTENCIA_POR_TIENDA_FROM_SQL
    + """
  AND EXISTS (SELECT 1 FROM #u_transfer ut WHERE ut.CodigoBarra = CAST(i.CodigoBarra AS VARCHAR(50)))
GROUP BY CAST(i.CodigoBarra AS VARCHAR(50));

CREATE UNIQUE CLUSTERED INDEX IX_u_existencia ON #u_existencia (CodigoBarra);
"""
)


def build_existencia_por_tienda_sql() -> str:
    """Existencia por codigo y tienda/bodega activa, con su nombre y tipo (1 tienda, 0 bodega).

    Parametro: codigos de barra separados por coma.
    """
    return (
        """
SELECT
      CAST(i.CodigoBarra AS VARCHAR(50)) AS CodigoBarra
    , CAST(t.dimid_tienda AS VARCHAR(20)) AS CodigoTienda
    , LTRIM(RTRIM(t.Nombre)) AS NombreTienda
    , t.Tipo AS TipoTienda
    , SUM(CASE WHEN h.[Existencia] < 0 THEN 0 ELSE ISNULL(h.[Existencia], 0) END) AS Existencia"""
        + EXISTENCIA_POR_TIENDA_FROM_SQL
        + """
  AND CAST(i.CodigoBarra AS VARCHAR(50)) IN (
        SELECT LTRIM(RTRIM([value]))
        FROM STRING_SPLIT(CAST(? AS VARCHAR(MAX)), ',')
  )
GROUP BY CAST(i.CodigoBarra AS VARCHAR(50)), t.dimid_tienda, LTRIM(RTRIM(t.Nombre)), t.Tipo
"""
    )


def build_tiendas_sql() -> str:
    """Tiendas (Tipo 1) y bodegas (Tipo 0) activas para el filtro de existencia."""
    return """
SELECT
      CAST(t.dimid_tienda AS VARCHAR(20)) AS Codigo
    , LTRIM(RTRIM(t.Nombre)) AS Nombre
    , LTRIM(RTRIM(t.Zona)) AS Zona
    , t.Tipo
FROM [BODEGA_DATOS].[dbo].[tbDimTiendas] AS t
WHERE t.Status = 1
ORDER BY t.Tipo, t.Nombre
"""


UNIFIED_FULL_SELECT_LIST = """
      CAST(base_query.CodigoBarra AS VARCHAR(50)) AS [Codigo Barra]
    , base_query.Referencia AS [Referencias]
    , base_query.CodigoMarca AS [Codigo Marca]
    , marca_detail.NombreMarca AS [Marca]
    , base_query.Nombre AS [Descripcion]
    , marca_detail.NombreMarca AS [Nombre Marca]
    , base_query.Fabricante AS [Codigo Fabricante]
    , base_query.NombreFabricante AS [Nombre Fabricante]
    , base_query.CodigoCategoria AS [Codigo Categoria]
    , base_query.NombreCategoria AS [Nombre Categoria]
    , base_query.CodigoLinea AS [Codigo Linea]
    , base_query.NombreLinea AS [Nombre Linea]
    , base_query.Usuario AS [Usuarios]
    , base_query.Documento AS [Numero de compra]
    , base_query.FechaFactura AS [Fecha Factura]
    , base_query.Observacion AS [Descripcion de compra]
    , base_query.CantidadDevuelta AS [Correcciones de compra]
    , base_query.Cantidad AS [Cantidad de compra]
    , base_query.[Suma Unidades Compra] AS [Suma Unidades Compras]
    , base_query.DespacharA AS [Despachar A]
    , base_query.NumeroContenedor AS [Numero Contenedor]
    , existencia_detail.ExistenciaTotal AS [Existencia actual]
    , existencia_detail.ExistenciaTotal AS [Suma Existencia]
    , CASE
        WHEN existencia_detail.ExistenciaTotal IS NULL OR existencia_detail.ExistenciaTotal = 0 THEN NULL
        ELSE (CAST(base_query.Cantidad AS FLOAT) / NULLIF(CAST(existencia_detail.ExistenciaTotal AS FLOAT), 0)) * 100
      END AS [Porcentaje de existencia%]
    , sales_detail.UnidadesVendidas AS [Unidades vendidas]
    , sales_detail.UnidadesVendidas AS [Suma Cantidades ventas]
    , CASE
        WHEN sales_detail.UnidadesVendidas IS NULL OR sales_detail.UnidadesVendidas = 0 THEN NULL
        ELSE (CAST(base_query.Cantidad AS FLOAT) / NULLIF(CAST(sales_detail.UnidadesVendidas AS FLOAT), 0)) * 100
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
        ELSE (CAST(base_query.Cantidad AS FLOAT) / NULLIF(CAST(kardex_detail.CostoInicial * ISNULL(sales_detail.UnidadesVendidas, 0) AS FLOAT), 0)) * 100
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
        ELSE (CAST(base_query.Cantidad AS FLOAT) / NULLIF(CAST(kardex_detail.AjustesPositivos AS FLOAT), 0)) * 100
      END AS [% Ajustes Positivos]
    , kardex_detail.AjustesNegativos AS [Unidades de Ajustes Negativos]
    , CASE
        WHEN kardex_detail.AjustesNegativos IS NULL OR kardex_detail.AjustesNegativos = 0 THEN NULL
        ELSE (CAST(base_query.Cantidad AS FLOAT) / NULLIF(CAST(kardex_detail.AjustesNegativos AS FLOAT), 0)) * 100
      END AS [% Ajustes Negativos]
    , kardex_detail.CostoInicial * ISNULL(kardex_detail.AjustesNegativos, 0) AS [Utilidad perdida por ajustes]
    , CASE
        WHEN (kardex_detail.CostoInicial * ISNULL(kardex_detail.AjustesNegativos, 0)) = 0 THEN NULL
        ELSE (CAST(base_query.Cantidad AS FLOAT) / NULLIF(CAST(kardex_detail.CostoInicial * ISNULL(kardex_detail.AjustesNegativos, 0) AS FLOAT), 0)) * 100
      END AS [% Utilidad perdida por ajustes]
    , transfer_detail.MATRIZ AS [Transferencia matriz]
    , transfer_detail.SUCURSAL AS [Transferencia sucursal]
    , transfer_detail.CodigoEnvia AS [Codigo envia]
    , transfer_detail.CodigoRecibe AS [Codigo recibe]
    , transfer_detail.FechaEmision AS [Fecha emision transferencia]
    , transfer_detail.FECHACARGATRANSFERENCIA AS [Fecha carga transferencia]
    , transfer_detail.Numero AS [Numero transferencia]
    , transfer_detail.dimid_tienda AS [Tienda kardex transferencia]
    , CASE
        WHEN ISNULL(base_query.[Suma Unidades Compra], 0) = 0 OR ISNULL(sales_detail.UnidadesVendidas, 0) <= 0 THEN NULL
        ELSE (CAST(sales_detail.UnidadesVendidas AS FLOAT) / CAST(base_query.[Suma Unidades Compra] AS FLOAT)) * 100
      END AS [Vendido]
    , CASE
        WHEN ISNULL(base_query.[Suma Unidades Compra], 0) = 0 OR ISNULL(sales_detail.UnidadesVendidas, 0) <= 0 THEN NULL
        ELSE base_query.[Suma Unidades Compra] - sales_detail.UnidadesVendidas
      END AS [Quedan]
"""


def build_unified_common_codes_sql() -> str:
    """Codigos que cumplen la regla de la unificada, ordenados. Parametros: fechaDesde, fechaHasta."""
    return UNIFIED_RULE_STEPS_SQL + """
SELECT CodigoBarra
FROM #u_transfer
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
    , DespacharA AS [Despachar A]
    , NumeroContenedor AS [Numero Contenedor]
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


def build_unified_full_sql(base_sql: str) -> str:
    """Consulta unificada completa del rango.

    Parametros, en orden: fechaDesde, fechaHasta (pasos con tablas temporales) y otra vez
    fechaDesde, fechaHasta (los dos ``?`` de la consulta base de compras).
    """
    return (
        UNIFIED_RULE_STEPS_SQL
        + UNIFIED_EXISTENCIA_STEP_SQL
        + f"""
SELECT{UNIFIED_FULL_SELECT_LIST}FROM ({base_sql}) AS base_query
INNER JOIN #u_sales AS sales_detail
    ON sales_detail.CodigoBarra = CAST(base_query.CodigoBarra AS VARCHAR(50))
INNER JOIN #u_transfer AS transfer_detail
    ON transfer_detail.CodigoBarra = CAST(base_query.CodigoBarra AS VARCHAR(50))
INNER JOIN #u_kardex AS kardex_detail
    ON kardex_detail.CodigoBarra = CAST(base_query.CodigoBarra AS VARCHAR(50))
LEFT JOIN #u_existencia AS existencia_detail
    ON existencia_detail.CodigoBarra = CAST(base_query.CodigoBarra AS VARCHAR(50))
OUTER APPLY
(
    SELECT TOP 1
          MC.[Nombre] AS NombreMarca
    FROM [J101010100_999911].[dbo].[MARCAS] AS MC
    WHERE CAST(MC.[Codigo] AS VARCHAR(50)) = CAST(base_query.CodigoMarca AS VARCHAR(50))
) AS marca_detail
ORDER BY base_query.CodigoBarra
"""
    )


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
