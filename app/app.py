"""
app.py — Aplicación principal de la plataforma RFID multi-reader FPT.

Funcionalidades:
  - Conexión simultánea a N readers (configurados en SQL Server).
  - Decodificación de EPC y persistencia en SQL Server en batch.
  - Panel web en tiempo real con WebSocket (lecturas, KPIs por reader/antena).
  - CRUD de readers y antenas desde la interfaz web (alta/baja/edición),
    sin necesidad de tocar archivos de configuración ni reiniciar el server.

Uso:
    1. Ejecutar sql/schema.sql contra una base de datos SQL Server vacía.
    2. Editar core/config.py con los datos de conexión a esa base.
    3. pip install -r requirements.txt
    4. python app.py
    5. Abrir http://localhost:5000 — desde ahí se pueden agregar readers.
"""

import logging
import sys
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO

sys.path.insert(0, str(Path(__file__).parent / "core"))

import config
import database
from epc_decoder import decodificar_epc
from rfid_manager import GestorMultiReader
from timestamp_utils import timestamp_llrp_a_datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("app")

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["SECRET_KEY"] = "rfid-plataforma-fpt"
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0  # evita que el navegador cachee JS/CSS viejos durante el desarrollo
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

buffer_lecturas = database.BufferLecturas(
    intervalo_flush_seg=config.INTERVALO_FLUSH_SEGUNDOS,
    tamano_maximo=config.TAMANO_MAXIMO_BUFFER,
)

# ── Estado en memoria para el panel (no reemplaza a la BD, es solo para
#    que la UI tenga algo que mostrar sin tener que consultar SQL Server
#    en cada evento) ────────────────────────────────────────────────────
ESTADO = {
    "eventos_recientes": deque(maxlen=300),
    "tags_unicos": set(),
    "lecturas_por_antena": defaultdict(int),
    "lecturas_por_reader": defaultdict(int),
    "estado_readers": {},  # reader_id -> {"nombre", "ip", "estado", "detalle"}
}
_lock_estado = threading.Lock()

gestor: GestorMultiReader = None  # se inicializa en main


def on_tag_report(reader_cfg, antena_id: int, tag: dict):
    """Callback invocado por cada tag leído, desde cualquiera de los hilos
    de reader activos. Decodifica, persiste en el buffer, y empuja al panel."""
    epc_hex, epc_ascii = decodificar_epc(tag)
    rssi = tag.get("PeakRSSI")
    tag_seen_count = tag.get("TagSeenCount")
    timestamp_dt = timestamp_llrp_a_datetime(tag)

    buffer_lecturas.agregar(
        antena_id=antena_id, epc_hex=epc_hex, epc_ascii=epc_ascii,
        rssi=rssi, tag_seen_count=tag_seen_count, timestamp_reader=timestamp_dt,
    )

    nombre_antena = next(
        (a.nombre for a in reader_cfg.antenas if a.antena_id == antena_id),
        f"Antena {antena_id}"
    )

    with _lock_estado:
        ESTADO["tags_unicos"].add(epc_hex)
        ESTADO["lecturas_por_antena"][antena_id] += 1
        ESTADO["lecturas_por_reader"][reader_cfg.reader_id] += 1

        registro = {
            "epc_hex": epc_hex,
            "epc_ascii": epc_ascii,
            "reader_id": reader_cfg.reader_id,
            "reader_nombre": reader_cfg.nombre,
            "antena_id": antena_id,
            "antena_nombre": nombre_antena,
            "rssi": rssi,
            "timestamp": timestamp_dt.isoformat(),
        }
        ESTADO["eventos_recientes"].appendleft(registro)

    socketio.emit("evento_lectura", registro)
    socketio.emit("kpis_actualizados", _construir_kpis())


def on_estado_reader(reader_cfg, estado: str, detalle: str):
    logger.info("Reader '%s' (%s): %s - %s", reader_cfg.nombre, reader_cfg.ip_address, estado, detalle)

    with _lock_estado:
        ESTADO["estado_readers"][reader_cfg.reader_id] = {
            "nombre": reader_cfg.nombre,
            "ip": reader_cfg.ip_address,
            "estado": estado,
            "detalle": detalle,
        }

    database.registrar_estado_reader(reader_cfg.reader_id, estado, detalle)
    socketio.emit("estado_reader", {
        "reader_id": reader_cfg.reader_id, "nombre": reader_cfg.nombre,
        "estado": estado, "detalle": detalle,
    })


def _construir_kpis() -> dict:
    with _lock_estado:
        return {
            "total_tags_unicos": len(ESTADO["tags_unicos"]),
            "total_lecturas": sum(ESTADO["lecturas_por_antena"].values()),
            "lecturas_por_reader": dict(ESTADO["lecturas_por_reader"]),
            "estado_readers": dict(ESTADO["estado_readers"]),
            "lecturas_pendientes_bd": buffer_lecturas.pendientes,
            "ultimo_error_bd": buffer_lecturas.ultimo_error,
        }


def _disparar_recarga_gestor():
    """Notifica al gestor multi-reader que recargue la configuración ahora,
    para que un alta/edición/baja hecha desde el panel tome efecto sin
    esperar al ciclo periódico."""
    if gestor is not None:
        gestor.recargar_ahora()


@app.errorhandler(404)
def manejar_404(e):
    logger.warning("404 Not Found: %s %s", request.method, request.path)
    return jsonify({"ok": False, "error": f"Ruta no encontrada: {request.path}"}), 404


# ── Rutas HTTP: panel principal ──────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/configuracion")
def pagina_configuracion():
    return render_template("configuracion.html")


@app.route("/informes")
def pagina_informes():
    return render_template("informes.html")


@app.route("/docs")
def pagina_docs():
    return render_template("docs.html")


# ── API REST: gestión de readers y antenas ────────────────────────────────
@app.route("/api/readers", methods=["GET"])
def api_listar_readers():
    readers = database.obtener_readers_activos()
    return jsonify([
        {
            "reader_id": r.reader_id, "nombre": r.nombre, "ip_address": r.ip_address,
            "puerto": r.puerto, "modelo": r.modelo, "ubicacion": r.ubicacion,
            "session_gen2": r.session_gen2, "tag_population": r.tag_population,
            "tx_power_dbm": r.tx_power_dbm,
            "antenas": [
                {
                    "antena_id": a.antena_id, "puerto_fisico": a.puerto_fisico,
                    "nombre": a.nombre, "ubicacion": a.ubicacion,
                }
                for a in r.antenas
            ],
        }
        for r in readers
    ])


@app.route("/api/readers", methods=["POST"])
def api_crear_reader():
    data = request.get_json(force=True)
    try:
        reader_id = database.crear_reader(
            nombre=data["nombre"],
            ip_address=data["ip_address"],
            puerto=int(data.get("puerto", 5084)),
            modelo=data.get("modelo"),
            ubicacion=data.get("ubicacion"),
            session_gen2=int(data.get("session_gen2", 2)),
            tag_population=int(data.get("tag_population", 4)),
            tx_power_dbm=data.get("tx_power_dbm"),
        )
        _disparar_recarga_gestor()
        return jsonify({"ok": True, "reader_id": reader_id})
    except Exception as e:
        logger.exception("Error creando reader")
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/readers/<int:reader_id>", methods=["PUT"])
def api_actualizar_reader(reader_id):
    data = request.get_json(force=True)
    try:
        database.actualizar_reader(reader_id, **data)
        _disparar_recarga_gestor()
        return jsonify({"ok": True})
    except Exception as e:
        logger.exception("Error actualizando reader %s", reader_id)
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/readers/<int:reader_id>", methods=["DELETE"])
def api_eliminar_reader(reader_id):
    try:
        database.eliminar_reader(reader_id)
        _disparar_recarga_gestor()
        return jsonify({"ok": True})
    except Exception as e:
        logger.exception("Error eliminando reader %s", reader_id)
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/readers/<int:reader_id>/antenas", methods=["POST"])
def api_crear_antena(reader_id):
    data = request.get_json(force=True)
    try:
        antena_id = database.crear_antena(
            reader_id=reader_id,
            puerto_fisico=int(data["puerto_fisico"]),
            nombre=data["nombre"],
            ubicacion=data.get("ubicacion"),
        )
        _disparar_recarga_gestor()
        return jsonify({"ok": True, "antena_id": antena_id})
    except Exception as e:
        logger.exception("Error creando antena para reader %s", reader_id)
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/antenas/<int:antena_id>", methods=["DELETE"])
def api_eliminar_antena(antena_id):
    try:
        database.eliminar_antena(antena_id)
        _disparar_recarga_gestor()
        return jsonify({"ok": True})
    except Exception as e:
        logger.exception("Error eliminando antena %s", antena_id)
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/db/test", methods=["GET"])
def api_probar_bd():
    ok, mensaje = database.probar_conexion()
    return jsonify({"ok": ok, "mensaje": mensaje})


# ── API: configuración del sistema (config.py en tiempo de ejecución) ────
@app.route("/api/config/sistema", methods=["GET"])
def api_obtener_config():
    """Devuelve los valores actuales de config.py como JSON, para mostrarlos
    en el panel de configuración del sistema sin exponer la contraseña."""
    return jsonify({
        "DB_DRIVER": config.DB_DRIVER,
        "DB_SERVER": config.DB_SERVER,
        "DB_DATABASE": config.DB_DATABASE,
        "DB_TRUSTED_CONNECTION": config.DB_TRUSTED_CONNECTION,
        "DB_USERNAME": config.DB_USERNAME,
        "DB_PASSWORD": "••••••" if config.DB_PASSWORD else "",
        "DB_ENCRYPT": config.DB_ENCRYPT,
        "DB_TRUST_SERVER_CERTIFICATE": config.DB_TRUST_SERVER_CERTIFICATE,
        "INTERVALO_FLUSH_SEGUNDOS": config.INTERVALO_FLUSH_SEGUNDOS,
        "TAMANO_MAXIMO_BUFFER": config.TAMANO_MAXIMO_BUFFER,
        "INTERVALO_RECARGA_CONFIG_SEGUNDOS": config.INTERVALO_RECARGA_CONFIG_SEGUNDOS,
        "SESSION_DEFAULT": config.SESSION_DEFAULT,
        "TAG_POPULATION_DEFAULT": config.TAG_POPULATION_DEFAULT,
        "REPORT_EVERY_N_TAGS": config.REPORT_EVERY_N_TAGS,
        "WEB_HOST": config.WEB_HOST,
        "WEB_PORT": config.WEB_PORT,
    })


@app.route("/api/config/sistema", methods=["POST"])
def api_guardar_config():
    """Persiste los valores editables de config.py en disco. Los cambios de
    conexión a BD y parámetros LLRP requieren reiniciar la app para tomar efecto;
    se informa claramente al cliente."""
    data = request.get_json(force=True)
    try:
        config_path = Path(__file__).parent / "core" / "config.py"
        lineas_nuevas = _generar_config_py(data)
        config_path.write_text(lineas_nuevas, encoding="utf-8")
        return jsonify({"ok": True, "requiere_reinicio": True,
                        "mensaje": "Configuración guardada. Reiniciá la aplicación para aplicar los cambios de conexión y parámetros LLRP."})
    except Exception as e:
        logger.exception("Error guardando config.py")
        return jsonify({"ok": False, "error": str(e)}), 500


def _generar_config_py(data: dict) -> str:
    """Genera el contenido del archivo config.py a partir de los valores del formulario."""
    def py_str(v): return f'"{v}"'
    def py_bool(v): return "True" if v else "False"

    password = data.get("DB_PASSWORD", "")
    if password == "••••••":
        password = config.DB_PASSWORD  # no sobrescribir si no se cambió

    return f'''"""
config.py — Configuración general de la plataforma RFID.
Editado desde el panel web. Requiere reinicio de la aplicación para tomar efecto.
"""

# ── Conexión a SQL Server ───────────────────────────────────────────────
DB_DRIVER = {py_str(data.get("DB_DRIVER", config.DB_DRIVER))}
DB_SERVER = {py_str(data.get("DB_SERVER", config.DB_SERVER))}
DB_DATABASE = {py_str(data.get("DB_DATABASE", config.DB_DATABASE))}

DB_TRUSTED_CONNECTION = {py_bool(data.get("DB_TRUSTED_CONNECTION", config.DB_TRUSTED_CONNECTION))}
DB_USERNAME = {py_str(data.get("DB_USERNAME", config.DB_USERNAME))}
DB_PASSWORD = {py_str(password)}

DB_ENCRYPT = {py_bool(data.get("DB_ENCRYPT", config.DB_ENCRYPT))}
DB_TRUST_SERVER_CERTIFICATE = {py_bool(data.get("DB_TRUST_SERVER_CERTIFICATE", config.DB_TRUST_SERVER_CERTIFICATE))}

# ── Buffer de inserts en batch ──────────────────────────────────────────
INTERVALO_FLUSH_SEGUNDOS = {float(data.get("INTERVALO_FLUSH_SEGUNDOS", config.INTERVALO_FLUSH_SEGUNDOS))}
TAMANO_MAXIMO_BUFFER = {int(data.get("TAMANO_MAXIMO_BUFFER", config.TAMANO_MAXIMO_BUFFER))}

# ── Recarga de configuración de readers ─────────────────────────────────
INTERVALO_RECARGA_CONFIG_SEGUNDOS = {int(data.get("INTERVALO_RECARGA_CONFIG_SEGUNDOS", config.INTERVALO_RECARGA_CONFIG_SEGUNDOS))}

# ── Parámetros LLRP por defecto ──────────────────────────────────────────
SESSION_DEFAULT = {int(data.get("SESSION_DEFAULT", config.SESSION_DEFAULT))}
TAG_POPULATION_DEFAULT = {int(data.get("TAG_POPULATION_DEFAULT", config.TAG_POPULATION_DEFAULT))}
REPORT_EVERY_N_TAGS = {int(data.get("REPORT_EVERY_N_TAGS", config.REPORT_EVERY_N_TAGS))}

# ── Servidor web ───────────────────────────────────────────────────────
WEB_HOST = {py_str(data.get("WEB_HOST", config.WEB_HOST))}
WEB_PORT = {int(data.get("WEB_PORT", config.WEB_PORT))}
'''


# ── API: informes estadísticos ────────────────────────────────────────────
@app.route("/api/informes/resumen_diario", methods=["GET"])
def api_resumen_diario():
    """Lecturas y tags únicos por día (últimos N días) para gráfico de tendencia."""
    dias = request.args.get("dias", 30, type=int)
    try:
        conn = database.obtener_conexion()
        cur = conn.cursor()
        cur.execute("""
            SELECT TOP (?)
                CAST(TimestampReader AS DATE) AS Fecha,
                COUNT(*) AS TotalLecturas,
                COUNT(DISTINCT EpcHex) AS TagsUnicos
            FROM dbo.LecturasRFID
            WHERE TimestampReader >= DATEADD(DAY, -?, SYSUTCDATETIME())
            GROUP BY CAST(TimestampReader AS DATE)
            ORDER BY Fecha DESC
        """, dias, dias)
        rows = [{"fecha": str(r[0]), "lecturas": r[1], "tags_unicos": r[2]}
                for r in cur.fetchall()]
        conn.close()
        return jsonify({"ok": True, "datos": list(reversed(rows))})
    except Exception as e:
        logger.exception("Error en resumen_diario")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/informes/por_antena", methods=["GET"])
def api_por_antena():
    """Total de lecturas y tags únicos por antena en el período seleccionado."""
    dias = request.args.get("dias", 30, type=int)
    try:
        conn = database.obtener_conexion()
        cur = conn.cursor()
        cur.execute("""
            SELECT
                A.Nombre AS NombreAntena,
                R.Nombre AS NombreReader,
                COUNT(*) AS TotalLecturas,
                COUNT(DISTINCT L.EpcHex) AS TagsUnicos
            FROM dbo.LecturasRFID L
            JOIN dbo.Antenas A ON A.AntenaId = L.AntenaId
            JOIN dbo.Readers R ON R.ReaderId = A.ReaderId
            WHERE L.TimestampReader >= DATEADD(DAY, -?, SYSUTCDATETIME())
            GROUP BY A.Nombre, R.Nombre
            ORDER BY TotalLecturas DESC
        """, dias)
        rows = [{"antena": r[0], "reader": r[1], "lecturas": r[2], "tags_unicos": r[3]}
                for r in cur.fetchall()]
        conn.close()
        return jsonify({"ok": True, "datos": rows})
    except Exception as e:
        logger.exception("Error en por_antena")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/informes/por_hora", methods=["GET"])
def api_por_hora():
    """Distribución de lecturas por hora del día (para detectar horarios pico)."""
    dias = request.args.get("dias", 7, type=int)
    try:
        conn = database.obtener_conexion()
        cur = conn.cursor()
        cur.execute("""
            SELECT
                DATEPART(HOUR, TimestampReader) AS Hora,
                COUNT(*) AS TotalLecturas
            FROM dbo.LecturasRFID
            WHERE TimestampReader >= DATEADD(DAY, -?, SYSUTCDATETIME())
            GROUP BY DATEPART(HOUR, TimestampReader)
            ORDER BY Hora
        """, dias)
        rows = [{"hora": r[0], "lecturas": r[1]} for r in cur.fetchall()]
        conn.close()
        return jsonify({"ok": True, "datos": rows})
    except Exception as e:
        logger.exception("Error en por_hora")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/informes/resumen_mensual", methods=["GET"])
def api_resumen_mensual():
    """Lecturas y tags únicos agrupados por mes (últimos 12 meses)."""
    try:
        conn = database.obtener_conexion()
        cur = conn.cursor()
        cur.execute("""
            SELECT TOP 12
                FORMAT(TimestampReader, 'yyyy-MM') AS Mes,
                COUNT(*) AS TotalLecturas,
                COUNT(DISTINCT EpcHex) AS TagsUnicos
            FROM dbo.LecturasRFID
            GROUP BY FORMAT(TimestampReader, 'yyyy-MM')
            ORDER BY Mes DESC
        """)
        rows = [{"mes": r[0], "lecturas": r[1], "tags_unicos": r[2]}
                for r in cur.fetchall()]
        conn.close()
        return jsonify({"ok": True, "datos": list(reversed(rows))})
    except Exception as e:
        logger.exception("Error en resumen_mensual")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/informes/kpis_generales", methods=["GET"])
def api_kpis_generales():
    """KPIs de alto nivel para el encabezado del dashboard gerencial."""
    try:
        conn = database.obtener_conexion()
        cur = conn.cursor()
        cur.execute("""
            SELECT
                COUNT(*) AS TotalLecturas,
                COUNT(DISTINCT EpcHex) AS TotalTagsUnicos,
                COUNT(DISTINCT AntenaId) AS AntenasActivas,
                CAST(MIN(TimestampReader) AS DATE) AS PrimeraLectura,
                CAST(MAX(TimestampReader) AS DATE) AS UltimaLectura
            FROM dbo.LecturasRFID
        """)
        r = cur.fetchone()
        hoy = None
        cur.execute("""
            SELECT COUNT(*) FROM dbo.LecturasRFID
            WHERE CAST(TimestampReader AS DATE) = CAST(SYSUTCDATETIME() AS DATE)
        """)
        hoy = cur.fetchone()[0]
        conn.close()
        return jsonify({"ok": True, "datos": {
            "total_lecturas": r[0], "total_tags_unicos": r[1],
            "antenas_activas": r[2],
            "primera_lectura": str(r[3]) if r[3] else None,
            "ultima_lectura": str(r[4]) if r[4] else None,
            "lecturas_hoy": hoy,
        }})
    except Exception as e:
        logger.exception("Error en kpis_generales")
        return jsonify({"ok": False, "error": str(e)}), 500


# ── Eventos SocketIO ────────────────────────────────────────────────────
@socketio.on("connect")
def al_conectar_cliente():
    with _lock_estado:
        eventos = list(ESTADO["eventos_recientes"])
    socketio.emit("estado_inicial", {
        "kpis": _construir_kpis(),
        "eventos_recientes": eventos,
    })


# ── Arranque ─────────────────────────────────────────────────────────────
def iniciar_plataforma():
    global gestor

    ok, mensaje = database.probar_conexion()
    if not ok:
        logger.error("=" * 70)
        logger.error("NO SE PUDO CONECTAR A SQL SERVER")
        logger.error("Detalle: %s", mensaje)
        logger.error("Revisar core/config.py (servidor, base de datos, credenciales)")
        logger.error("y que el esquema sql/schema.sql ya haya sido ejecutado.")
        logger.error("=" * 70)
    else:
        logger.info("Conexión a SQL Server OK: %s", mensaje)

    buffer_lecturas.iniciar()

    gestor = GestorMultiReader(on_tag_report=on_tag_report, on_estado=on_estado_reader)
    gestor.iniciar()

    def _heartbeat():
        while True:
            time.sleep(15)
            with _lock_estado:
                total = sum(ESTADO["lecturas_por_antena"].values())
            logger.info(
                "[heartbeat] lecturas_totales=%s | pendientes_bd=%s | readers_activos=%s",
                total, buffer_lecturas.pendientes, len(gestor.estado_actual()),
            )

    threading.Thread(target=_heartbeat, daemon=True, name="heartbeat").start()


if __name__ == "__main__":
    iniciar_plataforma()
    logger.info("Panel disponible en http://%s:%s", config.WEB_HOST, config.WEB_PORT)
    socketio.run(app, host=config.WEB_HOST, port=config.WEB_PORT, allow_unsafe_werkzeug=True)
