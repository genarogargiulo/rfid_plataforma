"""
config_writer.py — Genera el contenido de config.py a partir de una
configuración base (el módulo config ya cargado) más overrides puntuales.

Usado tanto por el panel web (Configuración → Guardar) como por el CLI de
setup de base de datos del instalador, para que ambos caminos escriban
siempre el mismo formato de archivo.
"""


def _py_str(v) -> str:
    return f'"{v}"'


def _py_bool(v) -> str:
    return "True" if v else "False"


def generar_config_py(base_config, overrides: dict = None) -> str:
    """Genera el contenido completo de config.py.

    base_config: módulo config ya cargado (valores por defecto para los
                 campos no incluidos en overrides).
    overrides:   dict con claves como DB_SERVER, DB_DATABASE, etc. que
                 pisan el valor de base_config.
    """
    overrides = overrides or {}

    def valor(clave, default_attr=None):
        if clave in overrides:
            return overrides[clave]
        return getattr(base_config, default_attr or clave)

    return f'''"""
config.py — Configuración general de la plataforma RFID.
Editado desde el panel web. Requiere reinicio de la aplicación para tomar efecto.
"""

# ── Conexión a SQL Server ───────────────────────────────────────────────
DB_DRIVER = {_py_str(valor("DB_DRIVER"))}
DB_SERVER = {_py_str(valor("DB_SERVER"))}
DB_DATABASE = {_py_str(valor("DB_DATABASE"))}

DB_TRUSTED_CONNECTION = {_py_bool(valor("DB_TRUSTED_CONNECTION"))}
DB_USERNAME = {_py_str(valor("DB_USERNAME"))}
DB_PASSWORD = {_py_str(valor("DB_PASSWORD"))}

DB_ENCRYPT = {_py_bool(valor("DB_ENCRYPT"))}
DB_TRUST_SERVER_CERTIFICATE = {_py_bool(valor("DB_TRUST_SERVER_CERTIFICATE"))}

# ── Buffer de inserts en batch ──────────────────────────────────────────
INTERVALO_FLUSH_SEGUNDOS = {float(valor("INTERVALO_FLUSH_SEGUNDOS"))}
TAMANO_MAXIMO_BUFFER = {int(valor("TAMANO_MAXIMO_BUFFER"))}

# ── Recarga de configuración de readers ─────────────────────────────────
INTERVALO_RECARGA_CONFIG_SEGUNDOS = {int(valor("INTERVALO_RECARGA_CONFIG_SEGUNDOS"))}

# ── Parámetros LLRP por defecto ──────────────────────────────────────────
SESSION_DEFAULT = {int(valor("SESSION_DEFAULT"))}
TAG_POPULATION_DEFAULT = {int(valor("TAG_POPULATION_DEFAULT"))}
REPORT_EVERY_N_TAGS = {int(valor("REPORT_EVERY_N_TAGS"))}

# ── Servidor web ───────────────────────────────────────────────────────
WEB_HOST = {_py_str(valor("WEB_HOST"))}
WEB_PORT = {int(valor("WEB_PORT"))}
'''
