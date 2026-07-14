"""
database.py — Capa de acceso a SQL Server. Maneja la conexión, inserts en
batch de lecturas RFID (para no saturar la BD con inserts de 1 fila por vez
cuando hay varios readers reportando en simultáneo), y consultas de
configuración (readers/antenas) que alimentan a la app al arrancar.

Requiere: pip install pyodbc
Requiere también el driver ODBC de SQL Server instalado en el sistema
(ver README para instrucciones de instalación en Windows).
"""

import logging
import re
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pyodbc

import config

logger = logging.getLogger("database")

# Nombre de BD/instancia: solo letras, números, guión bajo y backslash (instancia).
_RE_IDENTIFICADOR_SEGURO = re.compile(r"^[A-Za-z0-9_\\]+$")


def construir_connection_string(
    driver: str = None, server: str = None, database: str = None,
    trusted: bool = None, username: str = None, password: str = None,
    encrypt: bool = None, trust_server_certificate: bool = None,
) -> str:
    """Arma el connection string ODBC. Sin argumentos, usa config.py."""
    driver = config.DB_DRIVER if driver is None else driver
    server = config.DB_SERVER if server is None else server
    database = config.DB_DATABASE if database is None else database
    trusted = config.DB_TRUSTED_CONNECTION if trusted is None else trusted
    username = config.DB_USERNAME if username is None else username
    password = config.DB_PASSWORD if password is None else password
    encrypt = config.DB_ENCRYPT if encrypt is None else encrypt
    trust_server_certificate = (
        config.DB_TRUST_SERVER_CERTIFICATE if trust_server_certificate is None
        else trust_server_certificate
    )

    partes = [
        f"DRIVER={{{driver}}}",
        f"SERVER={server}",
        f"DATABASE={database}",
    ]
    if trusted:
        partes.append("Trusted_Connection=yes")
    else:
        partes.append(f"UID={username}")
        partes.append(f"PWD={password}")
    if encrypt is not None:
        partes.append(f"Encrypt={'yes' if encrypt else 'no'}")
    if trust_server_certificate:
        partes.append("TrustServerCertificate=yes")
    return ";".join(partes) + ";"


def obtener_conexion() -> pyodbc.Connection:
    """Abre una nueva conexión a SQL Server usando config.py. Lanza excepción si falla."""
    cs = construir_connection_string()
    return pyodbc.connect(cs, timeout=10)


def probar_conexion() -> tuple[bool, str]:
    """Prueba la conexión a la BD. Devuelve (ok, mensaje)."""
    try:
        conn = obtener_conexion()
        cur = conn.cursor()
        cur.execute("SELECT @@VERSION")
        version = cur.fetchone()[0]
        conn.close()
        return True, version.split("\n")[0]
    except Exception as e:
        return False, str(e)


# ── Configuración: Readers y Antenas ────────────────────────────────────

@dataclass
class AntenaConfig:
    antena_id: int
    reader_id: int
    puerto_fisico: int
    nombre: str
    ubicacion: Optional[str]
    activa: bool


@dataclass
class ReaderConfig:
    reader_id: int
    nombre: str
    ip_address: str
    puerto: int
    modelo: Optional[str]
    ubicacion: Optional[str]
    activo: bool
    session_gen2: int
    tag_population: int
    tx_power_dbm: Optional[int]
    antenas: list  # list[AntenaConfig]


def obtener_readers_activos() -> list:
    """Lee de la BD todos los readers activos junto con sus antenas activas."""
    conn = obtener_conexion()
    cur = conn.cursor()

    cur.execute("""
        SELECT ReaderId, Nombre, IpAddress, Puerto, Modelo, Ubicacion,
               Activo, SessionGen2, TagPopulation, TxPowerDbm
        FROM dbo.Readers
        WHERE Activo = 1
        ORDER BY ReaderId
    """)
    filas_readers = cur.fetchall()

    readers = []
    for fr in filas_readers:
        cur.execute("""
            SELECT AntenaId, ReaderId, PuertoFisico, Nombre, Ubicacion, Activa
            FROM dbo.Antenas
            WHERE ReaderId = ? AND Activa = 1
            ORDER BY PuertoFisico
        """, fr.ReaderId)
        filas_antenas = cur.fetchall()

        antenas = [
            AntenaConfig(
                antena_id=fa.AntenaId, reader_id=fa.ReaderId,
                puerto_fisico=fa.PuertoFisico, nombre=fa.Nombre,
                ubicacion=fa.Ubicacion, activa=bool(fa.Activa),
            )
            for fa in filas_antenas
        ]

        readers.append(ReaderConfig(
            reader_id=fr.ReaderId, nombre=fr.Nombre, ip_address=fr.IpAddress,
            puerto=fr.Puerto, modelo=fr.Modelo, ubicacion=fr.Ubicacion,
            activo=bool(fr.Activo), session_gen2=fr.SessionGen2,
            tag_population=fr.TagPopulation, tx_power_dbm=fr.TxPowerDbm,
            antenas=antenas,
        ))

    conn.close()
    return readers


def crear_reader(nombre, ip_address, puerto, modelo, ubicacion,
                  session_gen2=2, tag_population=4, tx_power_dbm=None) -> int:
    conn = obtener_conexion()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO dbo.Readers
            (Nombre, IpAddress, Puerto, Modelo, Ubicacion, SessionGen2, TagPopulation, TxPowerDbm)
        OUTPUT INSERTED.ReaderId
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, nombre, ip_address, puerto, modelo, ubicacion, session_gen2, tag_population, tx_power_dbm)
    reader_id = cur.fetchone()[0]
    conn.commit()
    conn.close()
    return reader_id


def actualizar_reader(reader_id, **campos):
    """Actualiza campos puntuales de un reader. campos: nombre_columna=valor."""
    if not campos:
        return
    columnas_validas = {
        "nombre": "Nombre", "ip_address": "IpAddress", "puerto": "Puerto",
        "modelo": "Modelo", "ubicacion": "Ubicacion", "activo": "Activo",
        "session_gen2": "SessionGen2", "tag_population": "TagPopulation",
        "tx_power_dbm": "TxPowerDbm",
    }
    sets = []
    valores = []
    for k, v in campos.items():
        col = columnas_validas.get(k)
        if col:
            sets.append(f"{col} = ?")
            valores.append(v)
    if not sets:
        return
    sets.append("FechaModificado = SYSUTCDATETIME()")
    valores.append(reader_id)

    conn = obtener_conexion()
    cur = conn.cursor()
    cur.execute(f"UPDATE dbo.Readers SET {', '.join(sets)} WHERE ReaderId = ?", *valores)
    conn.commit()
    conn.close()


def eliminar_reader(reader_id):
    """Desactiva (no borra físicamente) un reader. Las antenas y lecturas
    históricas se conservan para no romper trazabilidad."""
    conn = obtener_conexion()
    cur = conn.cursor()
    cur.execute("UPDATE dbo.Readers SET Activo = 0 WHERE ReaderId = ?", reader_id)
    conn.commit()
    conn.close()


def crear_antena(reader_id, puerto_fisico, nombre, ubicacion) -> int:
    conn = obtener_conexion()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO dbo.Antenas (ReaderId, PuertoFisico, Nombre, Ubicacion)
        OUTPUT INSERTED.AntenaId
        VALUES (?, ?, ?, ?)
    """, reader_id, puerto_fisico, nombre, ubicacion)
    antena_id = cur.fetchone()[0]
    conn.commit()
    conn.close()
    return antena_id


def eliminar_antena(antena_id):
    conn = obtener_conexion()
    cur = conn.cursor()
    cur.execute("UPDATE dbo.Antenas SET Activa = 0 WHERE AntenaId = ?", antena_id)
    conn.commit()
    conn.close()


def registrar_estado_reader(reader_id: int, estado: str, detalle: str):
    """Inserta una fila en el log de estado. No bloqueante en caso de error
    (un fallo de log no debe tirar abajo la app)."""
    try:
        conn = obtener_conexion()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO dbo.LogEstadoReaders (ReaderId, Estado, Detalle)
            VALUES (?, ?, ?)
        """, reader_id, estado, detalle[:500] if detalle else None)
        conn.commit()
        conn.close()
    except Exception:
        logger.exception("No se pudo registrar estado del reader %s en BD", reader_id)


# ── Buffer de inserts en batch para lecturas RFID ───────────────────────

class BufferLecturas:
    """
    Acumula lecturas en memoria y las inserta en SQL Server en lotes
    periódicos, en vez de hacer un INSERT por cada tag leído. Esto es
    importante con varios readers reportando en tiempo real: evita
    saturar la BD con miles de transacciones individuales por segundo.

    Si la BD se cae temporalmente, las lecturas se siguen acumulando en
    memoria (hasta un límite) y se reintenta el flush en el próximo ciclo.
    """

    def __init__(self, intervalo_flush_seg: float = 2.0, tamano_maximo: int = 50_000):
        self._cola = deque()
        self._lock = threading.Lock()
        self._intervalo = intervalo_flush_seg
        self._tamano_maximo = tamano_maximo
        self._hilo = None
        self._corriendo = False
        self._ultimo_error = None

    def agregar(self, antena_id: int, epc_hex: str, epc_ascii: Optional[str],
                rssi: Optional[int], tag_seen_count: Optional[int],
                timestamp_reader):
        with self._lock:
            if len(self._cola) >= self._tamano_maximo:
                logger.warning(
                    "Buffer de lecturas lleno (%d). Descartando lectura más vieja.",
                    self._tamano_maximo,
                )
                self._cola.popleft()
            self._cola.append((antena_id, epc_hex, epc_ascii, rssi, tag_seen_count, timestamp_reader))

    def _flush(self):
        with self._lock:
            if not self._cola:
                return 0
            lote = list(self._cola)
            self._cola.clear()

        try:
            conn = obtener_conexion()
            cur = conn.cursor()
            cur.fast_executemany = True
            cur.executemany("""
                INSERT INTO dbo.LecturasRFID
                    (AntenaId, EpcHex, EpcAscii, Rssi, TagSeenCount, TimestampReader)
                VALUES (?, ?, ?, ?, ?, ?)
            """, lote)
            conn.commit()
            conn.close()
            self._ultimo_error = None
            return len(lote)
        except Exception as e:
            logger.exception("Error al insertar lote de %d lecturas en SQL Server", len(lote))
            self._ultimo_error = str(e)
            # Reencolar el lote para reintentar en el próximo ciclo, respetando el límite
            with self._lock:
                for item in reversed(lote):
                    if len(self._cola) < self._tamano_maximo:
                        self._cola.appendleft(item)
            return 0

    def iniciar(self):
        if self._corriendo:
            return
        self._corriendo = True

        def _loop():
            while self._corriendo:
                time.sleep(self._intervalo)
                insertados = self._flush()
                if insertados:
                    logger.info("Lote insertado en SQL Server: %d lecturas", insertados)

        self._hilo = threading.Thread(target=_loop, daemon=True, name="buffer-lecturas-flush")
        self._hilo.start()

    def detener(self):
        self._corriendo = False
        self._flush()  # flush final antes de cerrar

    @property
    def pendientes(self) -> int:
        with self._lock:
            return len(self._cola)

    @property
    def ultimo_error(self) -> Optional[str]:
        return self._ultimo_error


# ── Usuarios ─────────────────────────────────────────────────────────────────

@dataclass
class UsuarioRow:
    usuario_id: int
    email: str
    nombre: str
    activo: bool
    rol: str = 'usuario'


def contar_usuarios() -> int:
    """Devuelve la cantidad de usuarios activos. Retorna -1 si la tabla no existe aún."""
    try:
        conn = obtener_conexion()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM dbo.Usuarios WHERE Activo = 1")
        n = cur.fetchone()[0]
        conn.close()
        return n
    except Exception:
        return -1


def obtener_usuario_por_id(usuario_id: int) -> Optional[UsuarioRow]:
    try:
        conn = obtener_conexion()
        cur = conn.cursor()
        cur.execute(
            "SELECT UsuarioId, Email, Nombre, Activo, Rol FROM dbo.Usuarios WHERE UsuarioId = ?",
            usuario_id,
        )
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        return UsuarioRow(usuario_id=row[0], email=row[1], nombre=row[2], activo=bool(row[3]), rol=row[4])
    except Exception:
        return None


def obtener_usuario_por_email(email: str):
    """Devuelve (UsuarioId, Email, Nombre, PasswordHash, Activo, Rol) o None."""
    try:
        conn = obtener_conexion()
        cur = conn.cursor()
        cur.execute(
            "SELECT UsuarioId, Email, Nombre, PasswordHash, Activo, Rol FROM dbo.Usuarios WHERE Email = ?",
            email,
        )
        row = cur.fetchone()
        conn.close()
        return row
    except Exception:
        return None


def crear_usuario(email: str, nombre: str, password_hash: str, rol: str = 'usuario') -> int:
    conn = obtener_conexion()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO dbo.Usuarios (Email, Nombre, PasswordHash, Rol)
        OUTPUT INSERTED.UsuarioId
        VALUES (?, ?, ?, ?)
    """, email, nombre, password_hash, rol)
    usuario_id = cur.fetchone()[0]
    conn.commit()
    conn.close()
    return usuario_id


def actualizar_ultimo_acceso(usuario_id: int):
    try:
        conn = obtener_conexion()
        cur = conn.cursor()
        cur.execute(
            "UPDATE dbo.Usuarios SET UltimoAcceso = SYSUTCDATETIME() WHERE UsuarioId = ?",
            usuario_id,
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def listar_usuarios() -> list:
    """Devuelve todos los usuarios (activos e inactivos) para el panel de administración."""
    conn = obtener_conexion()
    cur = conn.cursor()
    cur.execute("""
        SELECT UsuarioId, Email, Nombre, Activo, Rol,
               FechaCreacion, UltimoAcceso
        FROM dbo.Usuarios
        ORDER BY FechaCreacion
    """)
    rows = cur.fetchall()
    conn.close()
    return [
        {
            "usuario_id": r[0], "email": r[1], "nombre": r[2],
            "activo": bool(r[3]), "rol": r[4],
            "fecha_creacion": r[5].isoformat() if r[5] else None,
            "ultimo_acceso": r[6].isoformat() if r[6] else None,
        }
        for r in rows
    ]


def actualizar_usuario(usuario_id: int, nombre: str, email: str, rol: str, activo: bool):
    conn = obtener_conexion()
    cur = conn.cursor()
    cur.execute("""
        UPDATE dbo.Usuarios
        SET Nombre = ?, Email = ?, Rol = ?, Activo = ?
        WHERE UsuarioId = ?
    """, nombre, email.strip().lower(), rol, 1 if activo else 0, usuario_id)
    conn.commit()
    conn.close()


def cambiar_password_usuario(usuario_id: int, password_hash: str):
    conn = obtener_conexion()
    cur = conn.cursor()
    cur.execute(
        "UPDATE dbo.Usuarios SET PasswordHash = ? WHERE UsuarioId = ?",
        password_hash, usuario_id,
    )
    conn.commit()
    conn.close()


def contar_admins() -> int:
    """Cuenta cuántos usuarios activos tienen rol admin. Previene dejar el sistema sin admin."""
    try:
        conn = obtener_conexion()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM dbo.Usuarios WHERE Rol = 'admin' AND Activo = 1")
        n = cur.fetchone()[0]
        conn.close()
        return n
    except Exception:
        return 0


# ── Log de actividad ─────────────────────────────────────────────────────────

def registrar_actividad(
    usuario_id: Optional[int],
    email: Optional[str],
    accion: str,
    detalle: Optional[str],
    ip: Optional[str],
):
    """Inserta una fila en LogActividad. Nunca lanza excepción para no romper la app."""
    try:
        conn = obtener_conexion()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO dbo.LogActividad (UsuarioId, Email, Accion, Detalle, Ip)
            VALUES (?, ?, ?, ?, ?)
        """, usuario_id, email, accion[:100], detalle[:1000] if detalle else None, ip)
        conn.commit()
        conn.close()
    except Exception:
        logger.exception("No se pudo registrar actividad en BD")


# ── Setup inicial de base de datos (usado por el instalador) ─────────────────

# Fragmentos de mensaje de error de SQL Server que indican que el objeto
# (tabla/vista/índice) ya existe. Se toleran para que volver a correr el
# setup contra una BD ya inicializada no falle.
_ERRORES_OBJETO_YA_EXISTE = (
    "There is already an object named",
    "already an index named",
    "already exists",
)


def _identificador_seguro(valor: str) -> bool:
    return bool(_RE_IDENTIFICADOR_SEGURO.match(valor or ""))


def crear_base_datos_si_no_existe(
    driver: str, server: str, database: str,
    trusted: bool, username: str, password: str,
) -> None:
    """Se conecta a 'master' en el server dado y crea la BD si no existe.
    Lanza excepción si la conexión o la creación fallan."""
    if not _identificador_seguro(database):
        raise ValueError(f"Nombre de base de datos inválido: {database!r}")

    cs = construir_connection_string(
        driver=driver, server=server, database="master",
        trusted=trusted, username=username, password=password,
    )
    conn = pyodbc.connect(cs, timeout=10, autocommit=True)
    try:
        cur = conn.cursor()
        cur.execute(f"IF DB_ID(N'{database}') IS NULL CREATE DATABASE [{database}]")
    finally:
        conn.close()


def dividir_batches_sql(contenido: str) -> list:
    """Divide un script .sql en batches separados por líneas 'GO' (estilo sqlcmd/SSMS)."""
    batches = []
    actual = []
    for linea in contenido.splitlines():
        if re.match(r"^\s*GO\s*$", linea, re.IGNORECASE):
            if actual:
                batches.append("\n".join(actual))
                actual = []
        else:
            actual.append(linea)
    if actual:
        batches.append("\n".join(actual))
    return [b for b in batches if b.strip()]


def ejecutar_script_sql(conn: pyodbc.Connection, ruta: Path, log=None) -> None:
    """Ejecuta un archivo .sql batch por batch. Tolera errores de 'objeto ya
    existe' (permite re-ejecutar contra una BD ya inicializada); cualquier
    otro error se relanza."""
    log = log or (lambda *a: None)
    contenido = ruta.read_text(encoding="utf-8-sig")
    batches = dividir_batches_sql(contenido)
    cur = conn.cursor()
    for i, batch in enumerate(batches, start=1):
        if not batch.strip():
            continue
        try:
            cur.execute(batch)
            conn.commit()
        except pyodbc.Error as e:
            mensaje = str(e)
            if any(marcador in mensaje for marcador in _ERRORES_OBJETO_YA_EXISTE):
                log(f"  [{ruta.name}] batch {i}: objeto ya existe, se omite.")
                conn.rollback()
                continue
            log(f"  [{ruta.name}] batch {i}: ERROR — {mensaje}")
            raise


def setup_base_datos_desde_scripts(
    driver: str, server: str, database: str,
    trusted: bool, username: str, password: str,
    rutas_sql: list, log=None,
) -> None:
    """Orquesta el setup completo: crea la BD si no existe y ejecuta los
    scripts SQL en orden. Lanza excepción con mensaje descriptivo si algo
    falla (conexión, permisos, o error real de SQL no tolerado)."""
    log = log or (lambda *a: None)

    log(f"Conectando a '{server}' (master) para verificar/crear base de datos '{database}'...")
    crear_base_datos_si_no_existe(driver, server, database, trusted, username, password)
    log(f"Base de datos '{database}' verificada/creada.")

    cs = construir_connection_string(
        driver=driver, server=server, database=database,
        trusted=trusted, username=username, password=password,
    )
    conn = pyodbc.connect(cs, timeout=10)
    try:
        for ruta in rutas_sql:
            log(f"Ejecutando script: {ruta.name}...")
            ejecutar_script_sql(conn, ruta, log=log)
            log(f"Script {ruta.name} completado.")
    finally:
        conn.close()
