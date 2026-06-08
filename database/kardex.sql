SELECT
      MAX(T.Nombre) AS NombreTienda
    , MAX(K.[hecid_kardex]) AS hecid_kardex
    , MAX(T.[Nombre]) AS Nombre
    , MAX(K.[dimid_fechamovimiento]) AS dimid_fechamovimiento
    , MAX(H.[Nombre]) AS NombreArticulo
    , MAX(K.[Tipo]) AS Tipo
    , MAX(K.[Concepto]) AS Concepto
    , MAX(K.[MotivoAjuste]) AS MotivoAjuste
    , MAX(K.[FechaMovimiento]) AS FechaMovimiento
    , MAX(K.[Documento]) AS Documento
    , MAX(K.[Observacion]) AS Observacion
    , MAX(K.[Item]) AS Item
    , K.[CodigoBarra]
    , MAX(K.[Referencia]) AS Referencia
    , MAX(K.[CodigoMarca]) AS CodigoMarca
    , SUM(ISNULL(K.[Cantidad], 0)) AS Cantidad
    , MAX(I.[CostoInicial]) AS CostoInicial
    , MAX(K.[Existencia]) AS Existencia
    , SUM(ISNULL(K.[CantidadRM], 0)) AS CantidadRM
    , MAX(K.[ExistenciaRM]) AS ExistenciaRM
FROM [BODEGA_DATOS].[dbo].[tbHecKardex] K
INNER JOIN [BODEGA_DATOS].[dbo].[tbDimTiendas] T
    ON K.[dimid_tienda] = T.[dimid_tienda]
INNER JOIN [BODEGA_DATOS].[dbo].[tbHecInventario] I
    ON K.[dimid_inventario] = I.[dimid_inventario]
INNER JOIN [BODEGA_DATOS].[dbo].[tbDimInventario] H
    ON H.[dimid_inventario] = I.[dimid_inventario]
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
GROUP BY
      K.[CodigoBarra]
