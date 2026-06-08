/*
  Tabla resumen sugerida para escalar la consulta unificada en SQL Server.
  Este script solo crea la estructura e indices. No incluye procedimiento almacenado.
*/

USE [BODEGA_DATOS];
GO

IF OBJECT_ID('[dbo].[ConsultaUnificadaResumen]', 'U') IS NULL
CREATE TABLE [dbo].[ConsultaUnificadaResumen]
(
    [ResumenId] BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_ConsultaUnificadaResumen PRIMARY KEY,
    [FechaDesde] DATE NOT NULL,
    [FechaHasta] DATE NOT NULL,
    [CodigoBarra] VARCHAR(50) NOT NULL,
    [Referencias] VARCHAR(100) NULL,
    [CodigoMarca] VARCHAR(50) NULL,
    [Marca] VARCHAR(150) NULL,
    [Descripcion] VARCHAR(500) NULL,
    [NombreMarca] VARCHAR(150) NULL,
    [CodigoFabricante] VARCHAR(50) NULL,
    [NombreFabricante] VARCHAR(150) NULL,
    [CodigoCategoria] VARCHAR(50) NULL,
    [NombreCategoria] VARCHAR(150) NULL,
    [CodigoLinea] VARCHAR(50) NULL,
    [NombreLinea] VARCHAR(150) NULL,
    [CostoInicial] DECIMAL(18,4) NULL,
    [Usuarios] VARCHAR(100) NULL,
    [NumeroCompra] VARCHAR(100) NULL,
    [FechaFactura] DATETIME NULL,
    [DescripcionCompra] VARCHAR(500) NULL,
    [CorreccionesCompra] DECIMAL(18,4) NULL,
    [CantidadCompra] DECIMAL(18,4) NULL,
    [SumaUnidadesCompras] DECIMAL(18,4) NULL,
    [ExistenciaActual] DECIMAL(18,4) NULL,
    [PorcentajeExistencia] DECIMAL(18,4) NULL,
    [UnidadesVendidas] DECIMAL(18,4) NULL,
    [PorcentajeUnidadesVendidas] DECIMAL(18,4) NULL,
    [UnidadesAjustesPositivos] DECIMAL(18,4) NULL,
    [PorcentajeAjustesPositivos] DECIMAL(18,4) NULL,
    [UnidadesAjustesNegativos] DECIMAL(18,4) NULL,
    [PorcentajeAjustesNegativos] DECIMAL(18,4) NULL,
    [UtilidadPorVentas] DECIMAL(18,4) NULL,
    [PorcentajeUtilidadPorVentas] DECIMAL(18,4) NULL,
    [UtilidadPerdidaPorAjustes] DECIMAL(18,4) NULL,
    [PorcentajeUtilidadPerdidaPorAjustes] DECIMAL(18,4) NULL,
    [CreadoEn] DATETIME2 NOT NULL CONSTRAINT DF_ConsultaUnificadaResumen_CreadoEn DEFAULT SYSUTCDATETIME()
);
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = 'IX_ConsultaUnificadaResumen_Rango_CodigoBarra'
      AND object_id = OBJECT_ID('[dbo].[ConsultaUnificadaResumen]')
)
CREATE INDEX IX_ConsultaUnificadaResumen_Rango_CodigoBarra
ON [dbo].[ConsultaUnificadaResumen] ([FechaDesde], [FechaHasta], [CodigoBarra]);
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = 'IX_ConsultaUnificadaResumen_Rango_Marca_Categoria'
      AND object_id = OBJECT_ID('[dbo].[ConsultaUnificadaResumen]')
)
CREATE INDEX IX_ConsultaUnificadaResumen_Rango_Marca_Categoria
ON [dbo].[ConsultaUnificadaResumen] ([FechaDesde], [FechaHasta], [CodigoMarca], [CodigoCategoria])
INCLUDE ([Marca], [NombreMarca], [NombreCategoria], [UnidadesVendidas], [UnidadesAjustesPositivos], [UnidadesAjustesNegativos]);
GO
