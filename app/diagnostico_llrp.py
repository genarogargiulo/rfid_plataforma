"""
diagnostico_llrp.py — Script aislado para verificar si el reader está
realmente entregando tag reports, sin Flask ni lógica de dirección de por
medio. Útil para descartar si el problema está en la conexión LLRP o en
otra capa de la aplicación.

Uso:
    python diagnostico_llrp.py

Dejar corriendo unos 15-20 segundos con un tag RFID real pasando cerca
de una antena. Si no aparece NINGUNA línea "TAG LEIDO", el problema está
en la configuración del reader/antenas, no en la app web.
"""

import logging
import time

from sllurp.llrp import LLRPReaderClient, LLRPReaderConfig

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# <-- AJUSTAR a tu IP real
READER_IP = "192.168.0.118"
READER_PORT = 5084

# <-- AJUSTAR a las antenas físicamente conectadas
ANTENAS = [1, 2, 3, 4]

contador = {"total": 0, "antes_de_start": 0, "despues_de_start": 0}
estado_rospec = {"iniciado": False}


def callback_tags(reader, tag_reports):
    contador["total"] += len(tag_reports)
    if estado_rospec["iniciado"]:
        contador["despues_de_start"] += len(tag_reports)
    else:
        contador["antes_de_start"] += len(tag_reports)
    for tag in tag_reports:
        epc = tag.get("EPC-96") or tag.get("EPCData")
        if isinstance(epc, bytes):
            epc = epc.hex().upper()
        antena = tag.get("AntennaID")
        rssi = tag.get("PeakRSSI")
        marca = "POST-START" if estado_rospec["iniciado"] else "pre-start (buffer viejo)"
        print(f">>> TAG LEIDO [{marca}]  epc={epc}  antena={antena}  rssi={rssi}")


def callback_desconexion(*args, **kwargs):
    print(">>> DESCONECTADO del reader")


def main():
    cfg = LLRPReaderConfig()
    cfg.antennas = ANTENAS
    cfg.session = 2
    cfg.tag_population = 4
    cfg.start_inventory = True
    cfg.reset_on_connect = True
    cfg.report_every_n_tags = 1  # CRÍTICO: forzar reporte inmediato por cada tag
    cfg.tx_power = {ant: 0 for ant in ANTENAS}
    cfg.tag_content_selector = {
        'EnableROSpecID': False,
        'EnableSpecIndex': False,
        'EnableInventoryParameterSpecID': False,
        'EnableAntennaID': True,
        'EnableChannelIndex': False,
        'EnablePeakRSSI': True,
        'EnableFirstSeenTimestamp': False,
        'EnableLastSeenTimestamp': True,
        'EnableTagSeenCount': True,
        'EnableAccessSpecID': False,
    }

    reader = LLRPReaderClient(READER_IP, READER_PORT, config=cfg)
    reader.add_tag_report_callback(callback_tags)
    reader.add_disconnected_callback(callback_desconexion)

    print(f"Conectando a {READER_IP}:{READER_PORT} ...")
    reader.connect()
    estado_rospec["iniciado"] = True
    print("Conectado. ROSpec de inventario activo.")
    print("Esperando lecturas durante 40 segundos -- acercar y alejar el tag VARIAS veces.")

    for i in range(8):
        time.sleep(5)
        print(f"  ... {((i+1)*5)}s transcurridos | lecturas post-start hasta ahora: {contador['despues_de_start']}")

    print(f"\n=== RESUMEN ===")
    print(f"Lecturas ANTES de iniciar ROSpec (buffer viejo, ignorar): {contador['antes_de_start']}")
    print(f"Lecturas DESPUES de iniciar ROSpec (las que importan):    {contador['despues_de_start']}")

    if contador["despues_de_start"] == 0:
        print("\nPROBLEMA CONFIRMADO: el ROSpec no está entregando lecturas en vivo.")
        print("Las lecturas que viste antes (si las hubo) eran de un buffer/sesión vieja.")
    else:
        print("\nOK: el reader SI esta entregando lecturas en tiempo real con el ROSpec activo.")

    reader.disconnect()


if __name__ == "__main__":
    main()
