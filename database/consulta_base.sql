SELECT
      -- Datos del inventario
      M.[CodigoBarra]
    , I.[Referencia]
    , I.[CodigoMarca]
    , I.[Nombre]
    , I.[Talla]

    , I.[CodigoColor]
    , CO.[Nombre] AS NombreColor

    , I.[Fabricante]
    , FA.[Nombre] AS NombreFabricante

      -- Division de categoria
    , CAT.CodigoGenero
    , CG.[Nombre] AS NombreGenero

    , CAT.CodigoLinea
    , CL.[Nombre] AS NombreLinea

    , CAT.CodigoCategoria
    , CC.[Nombre] AS NombreCategoria

      -- Datos generales de la compra
    , C.[Documento]
    , C.[Proveedor]
    , C.[Fecha]
    , C.[FechaFactura]
    , C.[Observacion]
    , C.[Usuario]

      -- Datos del detalle de compra
    , M.[Cantidad]
    , M.[CantidadDevuelta]

      -- Suma total de unidades compradas para cada codigo de barra
    , SUM(ISNULL(M.[Cantidad], 0)) OVER (
        PARTITION BY M.[CodigoBarra]
      ) AS [Suma Unidades Compra]

FROM [J101010100_999911].[dbo].[COMPRAS] AS C

INNER JOIN [J101010100_999911].[dbo].[MOVCOMPRAS] AS M
    ON C.[Documento] = M.[Documento]
   AND C.[Proveedor] = M.[Proveedor]

LEFT JOIN [J101010100_999911].[dbo].[INVENTARIO] AS I
    ON M.[CodigoBarra] = I.[CodigoBarra]

OUTER APPLY
(
    SELECT
          CategoriaTexto  = CAST(I.[Categoria] AS VARCHAR(20))
        , CodigoGenero    = LEFT(CAST(I.[Categoria] AS VARCHAR(20)), 2)
        , CodigoLinea     = LEFT(CAST(I.[Categoria] AS VARCHAR(20)), 4)
        , CodigoCategoria = LEFT(CAST(I.[Categoria] AS VARCHAR(20)), 6)
) AS CAT

LEFT JOIN [J101010100_999911].[dbo].[COLORES] AS CO
    ON I.[CodigoColor] = CO.[Codigo]

LEFT JOIN [J101010100_999911].[dbo].[FABRICANTES] AS FA
    ON I.[Fabricante] = FA.[Codigo]

LEFT JOIN [J101010100_999911].[dbo].[CATEGORIAS] AS CG
    ON CAT.CodigoGenero = CAST(CG.[Codigo] AS VARCHAR(20))

LEFT JOIN [J101010100_999911].[dbo].[CATEGORIAS] AS CL
    ON CAT.CodigoLinea = CAST(CL.[Codigo] AS VARCHAR(20))

LEFT JOIN [J101010100_999911].[dbo].[CATEGORIAS] AS CC
    ON CAT.CodigoCategoria = CAST(CC.[Codigo] AS VARCHAR(20))

WHERE C.IDLote <> 001
  AND C.[Fecha] >= '2024-01-01'
  AND C.[Fecha] < DATEADD(DAY, 1, CAST(GETDATE() AS DATE))
