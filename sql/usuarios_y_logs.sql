/*
================================================================================
  usuarios_y_logs.sql — Gestión de usuarios y auditoría de actividad

  Ejecutar contra la misma base de datos donde ya se corrió schema.sql.

  Roles disponibles:
    'admin'   — acceso total (readers, antenas, config, gestión de usuarios)
    'usuario' — solo panel en vivo e informes (solo lectura)
================================================================================
*/

-- ── Usuarios del sistema ────────────────────────────────────────────────────
CREATE TABLE dbo.Usuarios (
    UsuarioId       INT IDENTITY(1,1)   PRIMARY KEY,
    Email           NVARCHAR(200)       NOT NULL,
    Nombre          NVARCHAR(100)       NOT NULL,
    PasswordHash    NVARCHAR(256)       NOT NULL,   -- Werkzeug scrypt/pbkdf2 hash
    Rol             NVARCHAR(20)        NOT NULL DEFAULT 'usuario',
    Activo          BIT                 NOT NULL DEFAULT 1,
    FechaCreacion   DATETIME2           NOT NULL DEFAULT SYSUTCDATETIME(),
    UltimoAcceso    DATETIME2           NULL,
    CONSTRAINT UQ_Usuarios_Email UNIQUE (Email),
    CONSTRAINT CK_Usuarios_Rol CHECK (Rol IN ('admin', 'usuario'))
);
GO

-- ── Migración: si la tabla ya existe sin la columna Rol, ejecutar esto:
-- ALTER TABLE dbo.Usuarios ADD Rol NVARCHAR(20) NOT NULL DEFAULT 'usuario'
--     CONSTRAINT CK_Usuarios_Rol CHECK (Rol IN ('admin', 'usuario'));
-- GO
-- -- Marcar al primer usuario existente como admin:
-- UPDATE dbo.Usuarios SET Rol = 'admin' WHERE UsuarioId = (SELECT MIN(UsuarioId) FROM dbo.Usuarios);
-- GO
GO

-- ── Log de actividad de usuarios ────────────────────────────────────────────
-- Registra cada acción relevante: logins, altas, bajas, cambios de config.
-- UsuarioId puede ser NULL para intentos de login fallidos con email inexistente.
CREATE TABLE dbo.LogActividad (
    LogId       BIGINT IDENTITY(1,1)  PRIMARY KEY,
    UsuarioId   INT                   NULL REFERENCES dbo.Usuarios(UsuarioId),
    Email       NVARCHAR(200)         NULL,
    Accion      NVARCHAR(100)         NOT NULL,
    Detalle     NVARCHAR(1000)        NULL,
    Ip          VARCHAR(45)           NULL,
    Timestamp   DATETIME2             NOT NULL DEFAULT SYSUTCDATETIME()
);
GO

CREATE INDEX IX_LogActividad_Timestamp ON dbo.LogActividad (Timestamp DESC);
CREATE INDEX IX_LogActividad_Usuario   ON dbo.LogActividad (UsuarioId, Timestamp DESC);
GO
