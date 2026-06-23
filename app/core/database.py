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
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional

import pyodbc

import config

logger = logging.getLogger("database")


def construir_connection_string() -> str:
    """Arma el connection string ODBC a partir de config.py."""
    partes = [
        f"DRIVER={{{config.DB_DRIVER}}}",
        f"SERVER={config.DB_SERVER}",
        f"DATABASE={config.DB_DATABASE}",
    ]
    if config.DB_TRUSTED_CONNECTION:
        partes.append("Trusted_Connection=yes")
    else:
        partes.append(f"UID={config.DB_USERNAME}")
        partes.append(f"PWD={config.DB_PASSWORD}")
    if config.DB_ENCRYPT is not None:
        partes.append(f"Encrypt={'yes' if config.DB_ENCRYPT else 'no'}")
    if config.DB_TRUST_SERVER_CERTIFICATE:
        partes.append("TrustServerCertificate=yes")
    return ";".join(partes) + ";"


def obtener_conexion() -> pyodbc.Connection:
    """Abre una nueva conexión a SQL Server. Lanza excepción si falla."""
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
