/*
================================================================================
  schema.sql — Esquema de base de datos para plataforma RFID FPT Córdoba

  Diseñado para:
    - Soportar N readers, cada uno con sus antenas configurables.
    - Registrar TODAS las lecturas (requerimiento del cliente: "guardar todo").
    - Ser explotado directamente por SQL / Power BI sin necesidad de pasar
      por la aplicación (requerimiento del cliente).
    - Permitir trazabilidad histórica para auditoría.

  Ejecutar este script una sola vez contra una base de datos vacía,
  por ejemplo: RFID_FPT
================================================================================
*/

-- ── Configuración: Readers ──────────────────────────────────────────────
-- Cada fila es un reader físico (R420 u otro modelo compatible LLRP).
CREATE TABLE dbo.Readers (
    ReaderId        INT IDENTITY(1,1)   PRIMARY KEY,
    Nombre          NVARCHAR(100)       NOT NULL,           -- ej: "Reader Rampa IVECO"
    IpAddress       VARCHAR(45)         NOT NULL,           -- IPv4 o IPv6
    Puerto          INT                 NOT NULL DEFAULT 5084,
    Modelo          NVARCHAR(50)        NULL,               -- ej: "Impinj R420"
    Ubicacion       NVARCHAR(200)       NULL,               -- texto libre: "Portón Expedición FPT"
    Activo          BIT                 NOT NULL DEFAULT 1,
    SessionGen2     TINYINT             NOT NULL DEFAULT 2, -- sesión Gen2 (0-3)
    TagPopulation   INT                 NOT NULL DEFAULT 4,
    TxPowerDbm      INT                 NULL,               -- NULL = máxima potencia
    FechaCreacion   DATETIME2           NOT NULL DEFAULT SYSUTCDATETIME(),
    FechaModificado DATETIME2           NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT UQ_Readers_Ip UNIQUE (IpAddress, Puerto)
);
GO

-- ── Configuración: Antenas ──────────────────────────────────────────────
-- Cada antena pertenece a un reader y tiene un número de puerto físico (1-4 típico).
CREATE TABLE dbo.Antenas (
    AntenaId        INT IDENTITY(1,1)   PRIMARY KEY,
    ReaderId        INT                 NOT NULL REFERENCES dbo.Readers(ReaderId),
    PuertoFisico    TINYINT             NOT NULL,           -- 1, 2, 3, 4...
    Nombre          NVARCHAR(100)       NOT NULL,           -- ej: "Antena Portón Expedición Ext."
    Ubicacion       NVARCHAR(200)       NULL,               -- texto libre, ej: "Portón 7,4m FPT"
    Activa          BIT                 NOT NULL DEFAULT 1,
    FechaCreacion   DATETIME2           NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT UQ_Antenas_ReaderPuerto UNIQUE (ReaderId, PuertoFisico)
);
GO

-- ── Eventos de lectura RFID ──────────────────────────────────────────────
-- Tabla principal: UNA fila por cada lectura de tag recibida. Append-only.
-- El cliente pidió "guardar todo" y explotar con Power BI / SQL directo,
-- por lo que esta tabla está desnormalizada en los campos de antena/reader
-- (vía la vista vw_Lecturas) para facilitar el reporting sin JOINs manuales.
CREATE TABLE dbo.LecturasRFID (
    LecturaId           BIGINT IDENTITY(1,1)  PRIMARY KEY,
    AntenaId            INT                   NOT NULL REFERENCES dbo.Antenas(AntenaId),
    EpcHex              VARCHAR(64)           NOT NULL,     -- EPC en hexadecimal, tal cual lo entrega el reader
    EpcAscii            VARCHAR(64)           NULL,         -- EPC decodificado como texto, si aplica
    Rssi                SMALLINT              NULL,         -- Peak RSSI en dBm (típicamente negativo)
    TagSeenCount        INT                   NULL,         -- veces vista en esta ráfaga de reporte
    TimestampReader     DATETIME2(6)          NOT NULL,     -- timestamp UTC que reporta el reader (LastSeenTimestampUTC)
    TimestampInsercion  DATETIME2(6)          NOT NULL DEFAULT SYSUTCDATETIME()  -- cuándo se insertó en BD
);
GO

-- Índices pensados para los patrones de consulta típicos de explotación:
-- por rango de fecha, por tag, y por antena/portón.
CREATE INDEX IX_LecturasRFID_Timestamp ON dbo.LecturasRFID (TimestampReader DESC);
CREATE INDEX IX_LecturasRFID_Epc       ON dbo.LecturasRFID (EpcHex, TimestampReader DESC);
CREATE INDEX IX_LecturasRFID_Antena    ON dbo.LecturasRFID (AntenaId, TimestampReader DESC);
GO

-- ── Log de eventos de conexión/estado de los readers ──────────────────────
-- Útil para diagnóstico y para que IT de planta pueda auditar caídas de
-- conexión sin tener que mirar logs de archivo en el servidor.
CREATE TABLE dbo.LogEstadoReaders (
    LogId           BIGINT IDENTITY(1,1)  PRIMARY KEY,
    ReaderId        INT                   NOT NULL REFERENCES dbo.Readers(ReaderId),
    Estado          VARCHAR(20)           NOT NULL,   -- 'conectando','conectado','desconectado','error'
    Detalle         NVARCHAR(500)         NULL,
    Timestamp       DATETIME2             NOT NULL DEFAULT SYSUTCDATETIME()
);
GO

CREATE INDEX IX_LogEstadoReaders_Reader ON dbo.LogEstadoReaders (ReaderId, Timestamp DESC);
GO

-- ================================================================================
-- VISTAS para explotación directa (Power BI / consultas SQL del cliente)
-- ================================================================================

-- Vista desnormalizada: una fila por lectura, con todos los datos legibles
-- (nombre de antena, nombre de reader, ubicación), sin necesidad de JOIN.
CREATE VIEW dbo.vw_Lecturas AS
SELECT
    L.LecturaId,
    L.EpcHex,
    L.EpcAscii,
    L.Rssi,
    L.TagSeenCount,
    L.TimestampReader,
    L.TimestampInsercion,
    A.AntenaId,
    A.Nombre        AS NombreAntena,
    A.PuertoFisico   AS PuertoFisicoAntena,
    A.Ubicacion      AS UbicacionAntena,
    R.ReaderId,
    R.Nombre        AS NombreReader,
    R.IpAddress      AS IpReader,
    R.Ubicacion      AS UbicacionReader
FROM dbo.LecturasRFID L
JOIN dbo.Antenas  A ON A.AntenaId = L.AntenaId
JOIN dbo.Readers  R ON R.ReaderId = A.ReaderId;
GO

-- Vista de KPIs diarios por antena: cantidad de lecturas y tags únicos por día.
-- Pensada para alimentar directamente un gráfico de Power BI sin transformación.
CREATE VIEW dbo.vw_ResumenDiarioPorAntena AS
SELECT
    CAST(L.TimestampReader AS DATE)    AS Fecha,
    A.AntenaId,
    A.Nombre                            AS NombreAntena,
    R.Nombre                            AS NombreReader,
    COUNT(*)                            AS TotalLecturas,
    COUNT(DISTINCT L.EpcHex)            AS TagsUnicos
FROM dbo.LecturasRFID L
JOIN dbo.Antenas A ON A.AntenaId = L.AntenaId
JOIN dbo.Readers R ON R.ReaderId = A.ReaderId
GROUP BY CAST(L.TimestampReader AS DATE), A.AntenaId, A.Nombre, R.Nombre;
GO

-- Vista de última lectura conocida por tag (útil para saber "dónde está" un
-- pallet la última vez que se vio, dado que no se trackea dirección/estado).
CREATE VIEW dbo.vw_UltimaLecturaPorTag AS
SELECT
    L.EpcHex,
    MAX(L.TimestampReader) AS UltimaVez
FROM dbo.LecturasRFID L
GROUP BY L.EpcHex;
GO

-- ================================================================================
-- Datos de ejemplo / semilla (OPCIONAL) — comentar o borrar si no se desea
-- ================================================================================
-- INSERT INTO dbo.Readers (Nombre, IpAddress, Puerto, Modelo, Ubicacion)
-- VALUES ('Reader Expedición FPT', '192.168.0.118', 5084, 'Impinj R420', 'Portón Expedición FPT');
--
-- INSERT INTO dbo.Antenas (ReaderId, PuertoFisico, Nombre, Ubicacion)
-- VALUES (1, 1, 'Antena Expedición 1', 'Portón Expedición FPT - lado A');
