"""
diagnostico_sql.py — Verifica la conexión a SQL Server de forma aislada,
sin levantar Flask ni conectar a ningún reader. Útil para confirmar que
el driver ODBC está instalado y que el connection string es correcto
antes de correr la aplicación completa.

Uso:
    cd app
    python diagnostico_sql.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "core"))

import config
import database


def main():
    print("Driver configurado:", config.DB_DRIVER)
    print("Servidor:", config.DB_SERVER)
    print("Base de datos:", config.DB_DATABASE)
    print("Autenticación:", "Windows (Trusted)" if config.DB_TRUSTED_CONNECTION else f"SQL Server (usuario: {config.DB_USERNAME})")
    print()

    print("Drivers ODBC instalados en este sistema:")
    try:
        import pyodbc
        for d in pyodbc.drivers():
            print(f"  - {d}")
    except Exception as e:
        print(f"  No se pudo listar drivers: {e}")
    print()

    print("Probando conexión...")
    ok, mensaje = database.probar_conexion()

    if ok:
        print(f"OK: conexión exitosa.")
        print(f"Versión del servidor: {mensaje}")
    else:
        print(f"ERROR: no se pudo conectar.")
        print(f"Detalle: {mensaje}")
        print()
        print("Posibles causas:")
        print("  - El driver ODBC indicado en config.py no está instalado")
        print("    (ver README.md para el link de descarga de Microsoft).")
        print("  - El nombre del servidor/instancia es incorrecto.")
        print("  - La base de datos 'RFID_FPT' no existe todavía")
        print("    (ejecutar sql/schema.sql primero contra una BD vacía).")
        print("  - SQL Server no tiene habilitada la autenticación elegida")
        print("    (Windows vs SQL Server Authentication).")
        sys.exit(1)

    print()
    print("Probando lectura de configuración de readers...")
    try:
        readers = database.obtener_readers_activos()
        print(f"OK: {len(readers)} reader(s) activo(s) encontrados en la base.")
        for r in readers:
            print(f"  - {r.nombre} ({r.ip_address}:{r.puerto}) - {len(r.antenas)} antena(s)")
    except Exception as e:
        print(f"ERROR leyendo readers: {e}")
        print("¿Se ejecutó sql/schema.sql contra esta base de datos?")
        sys.exit(1)


if __name__ == "__main__":
    main()
