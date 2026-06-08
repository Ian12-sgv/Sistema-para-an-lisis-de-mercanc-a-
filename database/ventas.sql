WITH VentasConsolidadas AS
(
    SELECT
          v.dimid_inventario
        , v.dimid_tienda
        , v.NumeroFactura
        , v.FechaVenta
        , v.TipoLista
        , v.Cantidad
        , SUM(ISNULL(v.[Cantidad], 0)) OVER(PARTITION BY v.dimid_inventario) AS TotalVentasArticulo
    FROM dbo.tbHecVentas AS v
    WHERE v.[FechaVenta] >= ?
      AND v.[FechaVenta] < DATEADD(DAY, 1, ?)
)
SELECT
      i.CodigoBarra AS CodigoBarra
    , i.Nombre AS Nombre
    , i.Referencia AS Referencia
    , t.Tipo AS Tipo
    , CAST(ROUND(c.PrecioDetal, 2) AS DECIMAL(18,2)) AS PrecioDetal
    , CAST(ROUND(c.CostoInicial, 2) AS DECIMAL(18,2)) AS CostoDolar
    , CAST(ROUND(c.PrecioMayor, 2) AS DECIMAL(18,2)) AS PrecioMayor
    , CAST(ROUND(c.CostoPromedio, 2) AS DECIMAL(18,2)) AS dolarMayor
    , CAST(ROUND(c.PrecioPromocion, 2) AS DECIMAL(18,2)) AS PrecioPromocion
    , t.Nombre AS Tienda
    , t.Zona AS Region
    , CASE
        WHEN h.Existencia < 0 THEN 0
        ELSE h.Existencia
      END AS Existencia
    , SUM(ISNULL(h.[Existencia], 0)) OVER (PARTITION BY i.[CodigoBarra]) AS [Suma Existencia]
    , v.Cantidad
    , ISNULL(v.TotalVentasArticulo, 0) AS [Suma Cantidades ventas]
    , v.NumeroFactura
    , v.FechaVenta
    , v.TipoLista
    , h.Status
FROM dbo.tbHecInventario AS h
INNER JOIN dbo.tbDimInventario AS i
    ON i.dimID_Inventario = h.dimid_inventario
INNER JOIN dbo.tbDimTiendas AS t
    ON t.dimid_tienda = h.dimid_tienda
INNER JOIN [J101010100_999911].[dbo].[Inventario] AS c
    ON c.CodigoBarra = i.CodigoBarra
INNER JOIN VentasConsolidadas AS v
    ON v.dimid_inventario = h.dimid_inventario
   AND v.dimid_tienda = h.dimid_tienda
WHERE
    t.dimID_Tienda <> '2010'
    AND t.Status = 1
    AND t.Tipo = 1
    AND (
        ? IS NULL
        OR CAST(i.CodigoBarra AS VARCHAR(50)) IN (
            SELECT LTRIM(RTRIM([value]))
            FROM STRING_SPLIT(CAST(? AS VARCHAR(MAX)), ',')
        )
    )
