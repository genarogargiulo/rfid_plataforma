"""
app.py — Aplicación principal de la plataforma RFID multi-reader.

Funcionalidades:
  - Conexión simultánea a N readers (configurados en SQL Server).
  - Decodificación de EPC y persistencia en SQL Server en batch.
  - Panel web en tiempo real con WebSocket (lecturas, KPIs por reader/antena).
  - CRUD de readers y antenas desde la interfaz web (alta/baja/edición),
    sin necesidad de tocar archivos de configuración ni reiniciar el server.
  - Gestión de usuarios con email/contraseña y sesiones permanentes.
  - Log de actividad de usuarios persistido en SQL Server.

Uso:
    1. Ejecutar sql/schema.sql contra una base de datos SQL Server vacía.
    2. Ejecutar sql/usuarios_y_logs.sql en la misma base de datos.
    3. Editar core/config.py con los datos de conexión a esa base.
    4. pip install -r requirements.txt
    5. python app.py
    6. Abrir http://localhost:5000 — crear el primer usuario en /setup.
"""

import argparse
import getpass
import importlib.util
import logging
import sys
import threading
import time
from collections import defaultdict, deque
from datetime import timedelta
from functools import wraps
from pathlib import Path

from flask import Flask, render_template, jsonify, request, redirect, url_for, session
from flask_login import (
    LoginManager, UserMixin,
    login_user, logout_user, login_required, current_user,
)
from flask_socketio import SocketIO
from werkzeug.security import generate_password_hash, check_password_hash

# ── Rutas de recursos: desarrollo vs. bundle PyInstaller (onedir) ─────────────
#
# En modo bundle:
#   sys._MEIPASS  = carpeta _internal/ con el bytecode y assets
#   sys.executable = ruta al .exe → su directorio es editable por el usuario
#
# config.py se carga SIEMPRE desde el sistema de archivos (nunca desde el
# bytecode del bundle) para que los cambios guardados desde el panel web
# persistan entre reinicios sin necesidad de recompilar.

def _resource_path(relative: str) -> str:
    """Ruta absoluta a un asset (templates, static). Funciona en dev y en bundle."""
    if hasattr(sys, '_MEIPASS'):
        return str(Path(sys._MEIPASS) / relative)
    return str(Path(__file__).parent / relative)


def _config_path() -> Path:
    """Ruta al config.py editable. En bundle va junto al .exe (directorio writable)."""
    if hasattr(sys, '_MEIPASS'):
        return Path(sys.executable).parent / "config.py"
    return Path(__file__).parent / "core" / "config.py"


def _sql_dir() -> Path:
    """Directorio con los scripts .sql (schema.sql, usuarios_y_logs.sql)."""
    if hasattr(sys, '_MEIPASS'):
        return Path(sys.executable).parent / "sql"
    return Path(__file__).parent.parent / "sql"


def _cargar_config():
    """
    Carga config.py desde el archivo en disco usando importlib, evitando el
    módulo congelado de PyInstaller. Así el panel web puede guardar cambios
    en config.py y al reiniciar la app los toma sin recompilar el bundle.
    """
    path = _config_path()
    spec = importlib.util.spec_from_file_location("config", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sys.modules["config"] = mod   # garantiza que 'import config' en otros módulos
    return mod                    # use esta versión (sys.modules tiene prioridad)


# Agregar core/ al path para los módulos de la app (database, epc_decoder, etc.)
if hasattr(sys, '_MEIPASS'):
    sys.path.insert(0, str(Path(sys._MEIPASS) / "core"))
else:
    sys.path.insert(0, str(Path(__file__).parent / "core"))

config = _cargar_config()  # ANTES de importar database (que hace 'import config')

import database
import config_writer
from epc_decoder import decodificar_epc
from rfid_manager import GestorMultiReader
from timestamp_utils import timestamp_llrp_a_datetime


def _logs_dir() -> Path:
    """Directorio de logs, junto al .exe en bundle o junto a app.py en dev."""
    d = _config_path().parent / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _configurar_logging():
    handlers = [logging.StreamHandler()]
    try:
        from logging.handlers import RotatingFileHandler
        handlers.append(RotatingFileHandler(
            _logs_dir() / "rfid_plataforma.log",
            maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8",
        ))
    except Exception:
        pass  # si no se puede escribir el log a archivo, seguir solo con stdout
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )


_configurar_logging()
logger = logging.getLogger("app")

app = Flask(
    __name__,
    template_folder=_resource_path("templates"),
    static_folder=_resource_path("static"),
)
app.config["SECRET_KEY"] = "rfid-plataforma-fpt"
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=3650)
app.config["REMEMBER_COOKIE_DURATION"] = timedelta(days=3650)

socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Iniciá sesión para acceder al panel."


# ── Modelo de usuario para Flask-Login ───────────────────────────────────────

class Usuario(UserMixin):
    def __init__(self, usuario_id: int, email: str, nombre: str, activo: bool, rol: str = 'usuario'):
        self.usuario_id = usuario_id
        self.email = email
        self.nombre = nombre
        self.activo = activo
        self.rol = rol

    @property
    def es_admin(self) -> bool:
        return self.rol == 'admin'

    def get_id(self):
        return str(self.usuario_id)


@login_manager.user_loader
def cargar_usuario(usuario_id: str):
    row = database.obtener_usuario_por_id(int(usuario_id))
    if row is None or not row.activo:
        return None
    return Usuario(row.usuario_id, row.email, row.nombre, row.activo, row.rol)


def admin_required(f):
    """Decorador: exige que el usuario autenticado tenga rol 'admin'."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.es_admin:
            if request.path.startswith('/api/'):
                return jsonify({"ok": False, "error": "Acceso denegado. Se requiere rol administrador."}), 403
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return decorated


# ── Helper de log de actividad ───────────────────────────────────────────────

def _log(accion: str, detalle: str = None):
    """Registra la acción del usuario autenticado actual. Nunca lanza excepción."""
    try:
        uid = current_user.usuario_id if current_user.is_authenticated else None
        email = current_user.email if current_user.is_authenticated else None
        database.registrar_actividad(uid, email, accion, detalle, request.remote_addr)
    except Exception:
        pass


# ── Buffer y estado en memoria ───────────────────────────────────────────────

buffer_lecturas = database.BufferLecturas(
    intervalo_flush_seg=config.INTERVALO_FLUSH_SEGUNDOS,
    tamano_maximo=config.TAMANO_MAXIMO_BUFFER,
)

ESTADO = {
    "eventos_recientes": deque(maxlen=300),
    "tags_unicos": set(),
    "lecturas_por_antena": defaultdict(int),
    "lecturas_por_reader": defaultdict(int),
    "estado_readers": {},
}
_lock_estado = threading.Lock()

gestor: GestorMultiReader = None


# ── Callbacks del gestor RFID ─────────────────────────────────────────────────

def on_tag_report(reader_cfg, antena_id: int, tag: dict):
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
    if gestor is not None:
        gestor.recargar_ahora()


# ── Manejo de errores ─────────────────────────────────────────────────────────

@app.errorhandler(404)
def manejar_404(e):
    logger.warning("404 Not Found: %s %s", request.method, request.path)
    return jsonify({"ok": False, "error": f"Ruta no encontrada: {request.path}"}), 404


# ── Rutas de autenticación ────────────────────────────────────────────────────

@app.route("/setup", methods=["GET", "POST"])
def setup():
    """Creación del primer usuario. Solo accesible cuando no existe ninguno."""
    if database.contar_usuarios() > 0:
        return redirect(url_for("login"))

    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        nombre = request.form.get("nombre", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")

        if not email or not nombre or not password:
            error = "Todos los campos son obligatorios."
        elif password != confirm:
            error = "Las contraseñas no coinciden."
        elif len(password) < 6:
            error = "La contraseña debe tener al menos 6 caracteres."
        else:
            try:
                ph = generate_password_hash(password)
                database.crear_usuario(email, nombre, ph, rol='admin')
                logger.info("Primer usuario (admin) creado: %s", email)
                return redirect(url_for("login"))
            except Exception as e:
                error = f"Error al crear usuario: {e}"

    return render_template("setup.html", error=error)


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if database.contar_usuarios() == 0:
        return redirect(url_for("setup"))

    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        row = database.obtener_usuario_por_email(email)

        if row and bool(row[4]) and check_password_hash(row[3], password):
            user = Usuario(row[0], row[1], row[2], bool(row[4]), row[5] if len(row) > 5 else 'usuario')
            session.permanent = True
            login_user(user, remember=True)
            database.actualizar_ultimo_acceso(user.usuario_id)
            database.registrar_actividad(
                user.usuario_id, user.email, "login", None, request.remote_addr
            )
            logger.info("Login exitoso: %s desde %s", email, request.remote_addr)
            next_page = request.args.get("next") or url_for("index")
            return redirect(next_page)
        else:
            database.registrar_actividad(
                None, email, "login_fallido", "Credenciales incorrectas", request.remote_addr
            )
            logger.warning("Login fallido para '%s' desde %s", email, request.remote_addr)
            error = "Email o contraseña incorrectos."

    return render_template("login.html", error=error)


@app.route("/logout")
@login_required
def logout():
    database.registrar_actividad(
        current_user.usuario_id, current_user.email, "logout", None, request.remote_addr
    )
    logger.info("Logout: %s", current_user.email)
    logout_user()
    return redirect(url_for("login"))


# ── Rutas HTTP: panel principal ───────────────────────────────────────────────

@app.route("/")
@login_required
def index():
    return render_template("index.html")


@app.route("/configuracion")
@login_required
@admin_required
def pagina_configuracion():
    return render_template("configuracion.html")


@app.route("/usuarios")
@login_required
@admin_required
def pagina_usuarios():
    return render_template("usuarios.html")


@app.route("/informes")
@login_required
def pagina_informes():
    return render_template("informes.html")


@app.route("/docs")
@login_required
def pagina_docs():
    return render_template("docs.html")


# ── API REST: gestión de readers y antenas ────────────────────────────────────

@app.route("/api/readers", methods=["GET"])
@login_required
@admin_required
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
@login_required
@admin_required
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
        _log("crear_reader", f"Reader '{data.get('nombre')}' (ID {reader_id}) — IP {data.get('ip_address')}")
        return jsonify({"ok": True, "reader_id": reader_id})
    except Exception as e:
        logger.exception("Error creando reader")
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/readers/<int:reader_id>", methods=["PUT"])
@login_required
@admin_required
def api_actualizar_reader(reader_id):
    data = request.get_json(force=True)
    try:
        database.actualizar_reader(reader_id, **data)
        _disparar_recarga_gestor()
        campos = ", ".join(f"{k}={v}" for k, v in data.items())
        _log("actualizar_reader", f"Reader ID {reader_id} — {campos}")
        return jsonify({"ok": True})
    except Exception as e:
        logger.exception("Error actualizando reader %s", reader_id)
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/readers/<int:reader_id>", methods=["DELETE"])
@login_required
@admin_required
def api_eliminar_reader(reader_id):
    try:
        database.eliminar_reader(reader_id)
        _disparar_recarga_gestor()
        _log("eliminar_reader", f"Reader ID {reader_id}")
        return jsonify({"ok": True})
    except Exception as e:
        logger.exception("Error eliminando reader %s", reader_id)
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/readers/<int:reader_id>/antenas", methods=["POST"])
@login_required
@admin_required
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
        _log("crear_antena", f"Antena '{data.get('nombre')}' (ID {antena_id}) en Reader {reader_id}")
        return jsonify({"ok": True, "antena_id": antena_id})
    except Exception as e:
        logger.exception("Error creando antena para reader %s", reader_id)
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/antenas/<int:antena_id>", methods=["DELETE"])
@login_required
@admin_required
def api_eliminar_antena(antena_id):
    try:
        database.eliminar_antena(antena_id)
        _disparar_recarga_gestor()
        _log("eliminar_antena", f"Antena ID {antena_id}")
        return jsonify({"ok": True})
    except Exception as e:
        logger.exception("Error eliminando antena %s", antena_id)
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/db/test", methods=["GET"])
@login_required
@admin_required
def api_probar_bd():
    ok, mensaje = database.probar_conexion()
    return jsonify({"ok": ok, "mensaje": mensaje})


# ── API: configuración del sistema ────────────────────────────────────────────

@app.route("/api/config/sistema", methods=["GET"])
@login_required
@admin_required
def api_obtener_config():
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
@login_required
@admin_required
def api_guardar_config():
    data = request.get_json(force=True)
    try:
        if data.get("DB_PASSWORD") == "••••••":
            data["DB_PASSWORD"] = config.DB_PASSWORD
        config_path = _config_path()
        lineas_nuevas = config_writer.generar_config_py(config, data)
        config_path.write_text(lineas_nuevas, encoding="utf-8")
        _log("guardar_config", f"Servidor: {data.get('DB_SERVER')}, BD: {data.get('DB_DATABASE')}")
        return jsonify({"ok": True, "requiere_reinicio": True,
                        "mensaje": "Configuración guardada. Reiniciá la aplicación para aplicar los cambios de conexión y parámetros LLRP."})
    except Exception as e:
        logger.exception("Error guardando config.py")
        return jsonify({"ok": False, "error": str(e)}), 500


# ── API: informes estadísticos ────────────────────────────────────────────────

@app.route("/api/informes/resumen_diario", methods=["GET"])
@login_required
def api_resumen_diario():
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
@login_required
def api_por_antena():
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
@login_required
def api_por_hora():
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
@login_required
def api_resumen_mensual():
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
@login_required
def api_kpis_generales():
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


# ── API: gestión de usuarios (solo admin) ────────────────────────────────────

@app.route("/api/usuarios", methods=["GET"])
@login_required
@admin_required
def api_listar_usuarios():
    return jsonify({"ok": True, "usuarios": database.listar_usuarios()})


@app.route("/api/usuarios", methods=["POST"])
@login_required
@admin_required
def api_crear_usuario():
    data = request.get_json(force=True)
    email = data.get("email", "").strip().lower()
    nombre = data.get("nombre", "").strip()
    password = data.get("password", "")
    rol = data.get("rol", "usuario")

    if not email or not nombre or not password:
        return jsonify({"ok": False, "error": "Email, nombre y contraseña son obligatorios."}), 400
    if len(password) < 6:
        return jsonify({"ok": False, "error": "La contraseña debe tener al menos 6 caracteres."}), 400
    if rol not in ("admin", "usuario"):
        return jsonify({"ok": False, "error": "Rol inválido."}), 400
    if database.obtener_usuario_por_email(email):
        return jsonify({"ok": False, "error": "Ya existe un usuario con ese email."}), 400

    try:
        ph = generate_password_hash(password)
        uid = database.crear_usuario(email, nombre, ph, rol)
        _log("crear_usuario", f"{nombre} <{email}> rol={rol}")
        logger.info("Usuario creado por admin %s: %s (rol=%s)", current_user.email, email, rol)
        return jsonify({"ok": True, "usuario_id": uid})
    except Exception as e:
        logger.exception("Error creando usuario")
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/usuarios/<int:usuario_id>", methods=["PUT"])
@login_required
@admin_required
def api_actualizar_usuario(usuario_id):
    data = request.get_json(force=True)
    nombre = data.get("nombre", "").strip()
    email = data.get("email", "").strip().lower()
    rol = data.get("rol", "usuario")
    activo = bool(data.get("activo", True))

    if not nombre or not email:
        return jsonify({"ok": False, "error": "Nombre y email son obligatorios."}), 400
    if rol not in ("admin", "usuario"):
        return jsonify({"ok": False, "error": "Rol inválido."}), 400

    # Evitar que el propio admin se quite el rol admin o se desactive
    if usuario_id == current_user.usuario_id:
        if rol != 'admin':
            return jsonify({"ok": False, "error": "No podés quitarte el rol administrador a vos mismo."}), 400
        if not activo:
            return jsonify({"ok": False, "error": "No podés desactivar tu propio usuario."}), 400

    # Evitar quedar sin ningún admin activo
    if rol != 'admin' or not activo:
        row = database.obtener_usuario_por_id(usuario_id)
        if row and row.rol == 'admin' and database.contar_admins() <= 1:
            return jsonify({"ok": False, "error": "Debe existir al menos un administrador activo."}), 400

    try:
        database.actualizar_usuario(usuario_id, nombre, email, rol, activo)
        _log("actualizar_usuario", f"ID {usuario_id} → nombre={nombre}, email={email}, rol={rol}, activo={activo}")
        return jsonify({"ok": True})
    except Exception as e:
        logger.exception("Error actualizando usuario %s", usuario_id)
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/usuarios/<int:usuario_id>/password", methods=["PUT"])
@login_required
@admin_required
def api_cambiar_password(usuario_id):
    data = request.get_json(force=True)
    password = data.get("password", "")
    if len(password) < 6:
        return jsonify({"ok": False, "error": "La contraseña debe tener al menos 6 caracteres."}), 400
    try:
        database.cambiar_password_usuario(usuario_id, generate_password_hash(password))
        _log("cambiar_password", f"Usuario ID {usuario_id}")
        return jsonify({"ok": True})
    except Exception as e:
        logger.exception("Error cambiando contraseña de usuario %s", usuario_id)
        return jsonify({"ok": False, "error": str(e)}), 500


# ── Eventos SocketIO ──────────────────────────────────────────────────────────

@socketio.on("connect")
def al_conectar_cliente():
    if not current_user.is_authenticated:
        return False  # rechaza conexión si no está autenticado

    with _lock_estado:
        eventos = list(ESTADO["eventos_recientes"])
    socketio.emit("estado_inicial", {
        "kpis": _construir_kpis(),
        "eventos_recientes": eventos,
    })


# ── Arranque ──────────────────────────────────────────────────────────────────

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


# ── CLI: setup de BD y utilidades de soporte (usadas por el instalador) ──────

def _escribir_log(path: Path, lineas: list):
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n".join(lineas) + "\n\n")
    except Exception:
        pass


def _cli_initdb(argv) -> int:
    """Crea (si no existe) la base de datos y ejecuta los scripts SQL.
    Pensado para ser invocado por el instalador (Inno Setup). Imprime a
    stdout y a logs/db_init.log. Devuelve el código de salida del proceso."""
    parser = argparse.ArgumentParser(prog="rfid_plataforma.exe initdb")
    parser.add_argument("--driver", default="ODBC Driver 17 for SQL Server")
    parser.add_argument("--server", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--trusted", action="store_true")
    parser.add_argument("--user", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--no-write-config", action="store_true",
                         help="No sobreescribir config.py con estos datos de conexión.")
    args = parser.parse_args(argv)

    log_path = _logs_dir() / "db_init.log"
    log_lineas = []

    def log(msg):
        print(msg)
        log_lineas.append(msg)

    log(f"=== Setup de base de datos — {time.strftime('%Y-%m-%d %H:%M:%S')} ===")
    autenticacion = "Windows" if args.trusted else f"SQL (usuario {args.user})"
    log(f"Servidor: {args.server}  Base de datos: {args.database}  Autenticación: {autenticacion}")

    rutas_sql = [_sql_dir() / "schema.sql", _sql_dir() / "usuarios_y_logs.sql"]
    faltantes = [r for r in rutas_sql if not r.exists()]
    if faltantes:
        log(f"ERROR: no se encontraron los scripts SQL: {[str(r) for r in faltantes]}")
        _escribir_log(log_path, log_lineas)
        return 4

    try:
        database.setup_base_datos_desde_scripts(
            driver=args.driver, server=args.server, database=args.database,
            trusted=args.trusted, username=args.user, password=args.password,
            rutas_sql=rutas_sql, log=log,
        )
    except Exception as e:
        log(f"ERROR: {e}")
        _escribir_log(log_path, log_lineas)
        return 2

    if not args.no_write_config:
        try:
            overrides = {
                "DB_DRIVER": args.driver, "DB_SERVER": args.server,
                "DB_DATABASE": args.database, "DB_TRUSTED_CONNECTION": args.trusted,
                "DB_USERNAME": args.user, "DB_PASSWORD": args.password,
            }
            _config_path().write_text(config_writer.generar_config_py(config, overrides), encoding="utf-8")
            log("config.py actualizado con los nuevos datos de conexión.")
        except Exception as e:
            log(f"ADVERTENCIA: no se pudo actualizar config.py: {e}")

    log("Setup de base de datos finalizado correctamente.")
    _escribir_log(log_path, log_lineas)
    return 0


def _cli_reset_admin_password() -> int:
    """Modo interactivo de consola para restablecer la contraseña de un
    usuario cuando se perdió el acceso al panel web. Se ejecuta con:
    rfid_plataforma.exe reset-admin-password"""
    print("=== Restablecer contraseña — Plataforma RFID ===")
    ok, mensaje = database.probar_conexion()
    if not ok:
        print(f"No se pudo conectar a la base de datos: {mensaje}")
        print("Revisá config.py (servidor, base de datos, credenciales) y reintentá.")
        return 1

    try:
        usuarios = database.listar_usuarios()
    except Exception as e:
        print(f"No se pudo obtener la lista de usuarios: {e}")
        return 1

    if not usuarios:
        print("No hay usuarios cargados todavía. Usá /setup en el panel web para crear el primer administrador.")
        return 1

    print("\nUsuarios existentes:")
    for u in usuarios:
        estado = "activo" if u["activo"] else "inactivo"
        print(f"  [{u['usuario_id']}] {u['email']} — {u['nombre']} ({u['rol']}, {estado})")

    email = input("\nEmail del usuario a restablecer: ").strip().lower()
    fila = database.obtener_usuario_por_email(email)
    if not fila:
        print("No existe un usuario con ese email.")
        return 1

    nueva = getpass.getpass("Nueva contraseña (mín. 6 caracteres): ")
    confirmar = getpass.getpass("Confirmar contraseña: ")
    if nueva != confirmar:
        print("Las contraseñas no coinciden.")
        return 1
    if len(nueva) < 6:
        print("La contraseña debe tener al menos 6 caracteres.")
        return 1

    database.cambiar_password_usuario(fila[0], generate_password_hash(nueva))
    print(f"Contraseña de '{email}' actualizada correctamente.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "initdb":
        sys.exit(_cli_initdb(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "reset-admin-password":
        sys.exit(_cli_reset_admin_password())

    iniciar_plataforma()
    logger.info("Panel disponible en http://%s:%s", config.WEB_HOST, config.WEB_PORT)
    socketio.run(app, host=config.WEB_HOST, port=config.WEB_PORT, allow_unsafe_werkzeug=True)
