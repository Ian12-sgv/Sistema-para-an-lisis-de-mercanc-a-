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
      AND (
          ? IS NULL
          OR CAST(CodigoBarra AS VARCHAR(50)) IN (
              SELECT LTRIM(RTRIM([value]))
              FROM STRING_SPLIT(CAST(? AS VARCHAR(MAX)), ',')
          )
      )
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
)
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
FROM FilteredMTF AS MTF
LEFT JOIN LatestK AS HK
    ON CAST(HK.CodigoBarra AS VARCHAR(50)) = CAST(MTF.CodigoBarra AS VARCHAR(50))
   AND CONVERT(VARCHAR(50), HK.Documento) = CONVERT(VARCHAR(50), MTF.Numero)
   AND HK.rn = 1
WHERE LOWER(LTRIM(RTRIM(HK.Concepto))) = 'transferencia'
ORDER BY MTF.FechaEmision, MTF.CodigoBarra, MTF.Numero
