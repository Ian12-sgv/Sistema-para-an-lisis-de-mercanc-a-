/*
  Scripts recomendados para mejorar consultas grandes en SQL Server.
  Ejecutar manualmente en SQL Server Management Studio con permisos adecuados.
  Revisa nombres de tablas/esquemas antes de aplicar en produccion.
*/

USE [J101010100_999911];
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = 'IX_COMPRAS_Fecha_Documento_Proveedor'
      AND object_id = OBJECT_ID('[dbo].[COMPRAS]')
)
CREATE INDEX IX_COMPRAS_Fecha_Documento_Proveedor
ON [dbo].[COMPRAS] ([Fecha], [Documento], [Proveedor])
INCLUDE ([FechaFactura], [Observacion], [Usuario], [IDLote]);
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = 'IX_MOVCOMPRAS_Documento_Proveedor_CodigoBarra'
      AND object_id = OBJECT_ID('[dbo].[MOVCOMPRAS]')
)
CREATE INDEX IX_MOVCOMPRAS_Documento_Proveedor_CodigoBarra
ON [dbo].[MOVCOMPRAS] ([Documento], [Proveedor], [CodigoBarra])
INCLUDE ([Cantidad], [CantidadDevuelta]);
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = 'IX_INVENTARIO_CodigoBarra'
      AND object_id = OBJECT_ID('[dbo].[INVENTARIO]')
)
CREATE INDEX IX_INVENTARIO_CodigoBarra
ON [dbo].[INVENTARIO] ([CodigoBarra])
INCLUDE ([Referencia], [CodigoMarca], [Nombre], [Talla], [CodigoColor], [Fabricante], [Categoria], [PrecioDetal], [CostoInicial], [PrecioMayor], [CostoPromedio], [PrecioPromocion]);
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = 'IX_MARCAS_Codigo'
      AND object_id = OBJECT_ID('[dbo].[MARCAS]')
)
CREATE INDEX IX_MARCAS_Codigo
ON [dbo].[MARCAS] ([Codigo])
INCLUDE ([Nombre]);
GO


USE [BODEGA_DATOS];
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = 'IX_tbHecVentas_Fecha_Inventario_Tienda'
      AND object_id = OBJECT_ID('[dbo].[tbHecVentas]')
)
CREATE INDEX IX_tbHecVentas_Fecha_Inventario_Tienda
ON [dbo].[tbHecVentas] ([FechaVenta], [dimid_inventario], [dimid_tienda])
INCLUDE ([Cantidad], [NumeroFactura], [TipoLista]);
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = 'IX_tbHecInventario_Inventario_Tienda'
      AND object_id = OBJECT_ID('[dbo].[tbHecInventario]')
)
CREATE INDEX IX_tbHecInventario_Inventario_Tienda
ON [dbo].[tbHecInventario] ([dimid_inventario], [dimid_tienda])
INCLUDE ([Existencia], [Status], [CostoInicial]);
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = 'IX_tbDimInventario_CodigoBarra'
      AND object_id = OBJECT_ID('[dbo].[tbDimInventario]')
)
CREATE INDEX IX_tbDimInventario_CodigoBarra
ON [dbo].[tbDimInventario] ([CodigoBarra])
INCLUDE ([dimID_Inventario], [Nombre], [Referencia]);
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = 'IX_tbDimTiendas_Tienda_Status_Tipo'
      AND object_id = OBJECT_ID('[dbo].[tbDimTiendas]')
)
CREATE INDEX IX_tbDimTiendas_Tienda_Status_Tipo
ON [dbo].[tbDimTiendas] ([dimid_tienda], [Status], [Tipo])
INCLUDE ([Nombre], [Zona]);
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = 'IX_tbHecKardex_CodigoBarra_FechaMovimiento'
      AND object_id = OBJECT_ID('[dbo].[tbHecKardex]')
)
CREATE INDEX IX_tbHecKardex_CodigoBarra_FechaMovimiento
ON [dbo].[tbHecKardex] ([CodigoBarra], [FechaMovimiento])
INCLUDE ([hecid_kardex], [dimid_tienda], [dimid_inventario], [Tipo], [Concepto], [MotivoAjuste], [Documento], [Observacion], [Item], [Referencia], [CodigoMarca], [Cantidad], [Existencia], [CantidadRM], [ExistenciaRM]);
GO


/*
  Indices por rango de fecha (agregados 2026-11-11).

  Las consultas de kardex y transferencias filtran primero por fecha y sin codigo de barra.
  El indice IX_tbHecKardex_CodigoBarra_FechaMovimiento empieza por CodigoBarra, asi que no
  sirve para esos filtros y SQL Server termina recorriendo la tabla completa.

  Son indices filtrados: solo contienen las filas que las consultas usan
  (ajustes con MotivoAjuste y transferencias con CodigoBarra), por eso ocupan menos.

  Crearlos sobre tablas grandes bloquea escrituras mientras dura la creacion:
  ejecutar fuera del horario de carga de datos.
*/

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = 'IX_tbHecKardex_FechaMovimiento_Ajustes'
      AND object_id = OBJECT_ID('[dbo].[tbHecKardex]')
)
CREATE INDEX IX_tbHecKardex_FechaMovimiento_Ajustes
ON [dbo].[tbHecKardex] ([FechaMovimiento])
INCLUDE ([CodigoBarra], [hecid_kardex], [dimid_fechamovimiento], [dimid_tienda], [dimid_inventario], [Tipo], [Concepto], [MotivoAjuste], [Documento], [Observacion], [Item], [Referencia], [CodigoMarca], [Cantidad], [Existencia], [CantidadRM], [ExistenciaRM])
WHERE [MotivoAjuste] IS NOT NULL;
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = 'IX_MOVTRANSFERECIAS_TIENDAS_FechaEmision'
      AND object_id = OBJECT_ID('[dbo].[MOVTRANSFERECIAS_TIENDAS]')
)
CREATE INDEX IX_MOVTRANSFERECIAS_TIENDAS_FechaEmision
ON [dbo].[MOVTRANSFERECIAS_TIENDAS] ([FechaEmision])
INCLUDE ([CodigoBarra], [Numero], [MATRIZ], [SUCURSAL], [CodigoEnvia], [CodigoRecibe], [FECHACARGATRANSFERENCIA])
WHERE [CodigoBarra] IS NOT NULL;
GO

/*
  Verificacion: indices existentes en las tablas de este script.
  Si alguno de los anteriores no aparece, el script no se ha ejecutado en este servidor.
*/
SELECT OBJECT_NAME(i.object_id) AS Tabla, i.name AS Indice, i.has_filter AS Filtrado
FROM sys.indexes AS i
WHERE i.name LIKE 'IX[_]%'
  AND OBJECT_NAME(i.object_id) IN ('tbHecVentas', 'tbHecInventario', 'tbDimInventario', 'tbDimTiendas', 'tbHecKardex', 'MOVTRANSFERECIAS_TIENDAS')
ORDER BY Tabla, Indice;
GO
