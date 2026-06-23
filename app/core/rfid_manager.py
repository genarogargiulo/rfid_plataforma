"""
rfid_manager.py — Administra conexiones LLRP a múltiples readers en
paralelo (uno por hilo), y centraliza el procesamiento de tag reports
hacia el buffer de base de datos y hacia el panel web en tiempo real.

Reemplaza al cliente de un solo reader de la versión anterior: ahora la
lista de readers a conectar viene de la base de datos (dbo.Readers),
permitiendo agregar/quitar readers sin tocar código ni reiniciar la app
manualmente (se recarga periódicamente).
"""

import logging
import threading
import time
from typing import Callable, Optional

from sllurp.llrp import LLRPReaderClient, LLRPReaderConfig

import config
import database

logger = logging.getLogger("rfid_manager")


class ConexionReader:
    """Maneja la conexión LLRP a UN reader físico, en su propio hilo."""

    def __init__(self, reader_cfg: "database.ReaderConfig",
                 on_tag_report: Callable, on_estado: Callable):
        self.reader_cfg = reader_cfg
        self._on_tag_report = on_tag_report
        self._on_estado = on_estado
        self._reader: Optional[LLRPReaderClient] = None
        self._hilo: Optional[threading.Thread] = None
        self._detener_flag = False
        self.conectado = False

        # Mapeo puerto físico de antena -> antena_id (BD), para poder
        # resolver de qué antena vino cada lectura sin otra consulta a BD.
        self.puerto_a_antena_id = {
            a.puerto_fisico: a.antena_id for a in reader_cfg.antenas
        }

    def _antenas_activas(self) -> list:
        return [a.puerto_fisico for a in self.reader_cfg.antenas]

    def _factory_llrp_config(self) -> LLRPReaderConfig:
        cfg = LLRPReaderConfig()
        antenas = self._antenas_activas()
        if not antenas:
            raise ValueError(f"Reader '{self.reader_cfg.nombre}' no tiene antenas activas configuradas")

        cfg.antennas = antenas
        cfg.session = self.reader_cfg.session_gen2 or config.SESSION_DEFAULT
        cfg.tag_population = self.reader_cfg.tag_population or config.TAG_POPULATION_DEFAULT
        cfg.start_inventory = True
        cfg.reset_on_connect = True
        cfg.reconnect = False  # el reintento lo manejamos nosotros en el loop externo

        # CRÍTICO: sin esto, el reader nunca dispara el reporte de tags en
        # inventario continuo (ver notas en README). Forzado a 1 siempre.
        cfg.report_every_n_tags = config.REPORT_EVERY_N_TAGS

        potencia = self.reader_cfg.tx_power_dbm if self.reader_cfg.tx_power_dbm is not None else 0
        cfg.tx_power = {ant: potencia for ant in antenas}

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
        return cfg

    def _callback_tag_report(self, reader, tag_reports):
        for tag in tag_reports:
            puerto_fisico = tag.get("AntennaID")
            antena_id = self.puerto_a_antena_id.get(puerto_fisico)
            if antena_id is None:
                # Antena no registrada en BD para este reader; se ignora
                # la lectura (puede pasar si se conectó una antena no
                # configurada todavía en el panel).
                continue
            try:
                self._on_tag_report(self.reader_cfg, antena_id, tag)
            except Exception:
                logger.exception(
                    "Error procesando tag report de reader '%s'", self.reader_cfg.nombre
                )

    def _callback_desconexion(self, *args, **kwargs):
        self.conectado = False
        self._on_estado(self.reader_cfg, "desconectado", "Conexión perdida con el reader")

    def conectar_y_correr(self):
        """Bloquea el hilo actual hasta que se pierda la conexión o se llame a detener()."""
        try:
            cfg = self._factory_llrp_config()
        except ValueError as e:
            self._on_estado(self.reader_cfg, "error", str(e))
            time.sleep(10)  # evita loop de error apretado si no hay antenas
            return

        self._reader = LLRPReaderClient(
            self.reader_cfg.ip_address, self.reader_cfg.puerto, config=cfg
        )
        self._reader.add_tag_report_callback(self._callback_tag_report)
        self._reader.add_disconnected_callback(self._callback_desconexion)

        self._on_estado(
            self.reader_cfg, "conectando",
            f"Conectando a {self.reader_cfg.ip_address}:{self.reader_cfg.puerto} ..."
        )

        try:
            self._reader.connect()
            self.conectado = True
            self._on_estado(
                self.reader_cfg, "conectado",
                f"Conectado a {self.reader_cfg.ip_address}:{self.reader_cfg.puerto}"
            )
            self._reader.join()
        except Exception as e:
            logger.exception("Error de conexión con reader '%s'", self.reader_cfg.nombre)
            self._on_estado(self.reader_cfg, "error", str(e))
        finally:
            self.conectado = False

    def iniciar_en_hilo(self):
        def _loop():
            while not self._detener_flag:
                try:
                    self.conectar_y_correr()
                except Exception:
                    logger.exception("Excepción no controlada en reader '%s'", self.reader_cfg.nombre)
                if self._detener_flag:
                    break
                logger.warning(
                    "Reader '%s' desconectado. Reintentando en 5s...", self.reader_cfg.nombre
                )
                time.sleep(5)

        self._hilo = threading.Thread(
            target=_loop, daemon=True, name=f"reader-{self.reader_cfg.reader_id}"
        )
        self._hilo.start()

    def detener(self):
        self._detener_flag = True
        if self._reader is not None:
            try:
                self._reader.disconnect()
            except Exception:
                pass


class GestorMultiReader:
    """
    Mantiene una ConexionReader por cada reader activo en la BD, y
    recarga periódicamente la configuración para detectar altas/bajas
    de readers hechas desde el panel web sin reiniciar la aplicación.
    """

    def __init__(self, on_tag_report: Callable, on_estado: Callable):
        self._on_tag_report = on_tag_report
        self._on_estado = on_estado
        self._conexiones: dict = {}  # reader_id -> ConexionReader
        self._lock = threading.Lock()
        self._corriendo = False

    def _reader_ids_activos(self) -> set:
        with self._lock:
            return set(self._conexiones.keys())

    def _firma_antenas(self, reader_cfg) -> tuple:
        """Genera una firma comparable de la config de antenas de un reader,
        para detectar si cambió desde la última vez que se conectó."""
        return tuple(sorted(a.puerto_fisico for a in reader_cfg.antenas))

    def _recargar_configuracion(self):
        try:
            readers_bd = database.obtener_readers_activos()
        except Exception:
            logger.exception("No se pudo leer configuración de readers desde la BD")
            return

        ids_bd = {r.reader_id for r in readers_bd}
        ids_actuales = self._reader_ids_activos()

        # Dar de baja conexiones de readers que ya no están activos en BD
        for reader_id in ids_actuales - ids_bd:
            logger.info("Deteniendo conexión a reader_id=%s (ya no activo en BD)", reader_id)
            with self._lock:
                conexion = self._conexiones.pop(reader_id, None)
            if conexion:
                conexion.detener()

        # Reconectar readers existentes cuya lista de antenas cambió
        # (alta/baja de antena desde el panel) — el ROSpec LLRP solo se
        # arma una vez al conectar, así que un cambio de antenas requiere
        # reconexión para tomar efecto.
        for r in readers_bd:
            if r.reader_id in ids_actuales:
                with self._lock:
                    conexion_actual = self._conexiones.get(r.reader_id)
                if conexion_actual and self._firma_antenas(r) != self._firma_antenas(conexion_actual.reader_cfg):
                    logger.info(
                        "Antenas modificadas para reader '%s'. Reconectando para aplicar cambios.",
                        r.nombre,
                    )
                    conexion_actual.detener()
                    nueva_conexion = ConexionReader(r, self._on_tag_report, self._on_estado)
                    with self._lock:
                        self._conexiones[r.reader_id] = nueva_conexion
                    nueva_conexion.iniciar_en_hilo()

        # Iniciar conexiones para readers nuevos
        for r in readers_bd:
            if r.reader_id not in ids_actuales:
                logger.info("Iniciando conexión a reader nuevo: %s (%s)", r.nombre, r.ip_address)
                conexion = ConexionReader(r, self._on_tag_report, self._on_estado)
                with self._lock:
                    self._conexiones[r.reader_id] = conexion
                conexion.iniciar_en_hilo()

    def iniciar(self):
        self._corriendo = True
        self._recargar_configuracion()

        def _loop_recarga():
            while self._corriendo:
                time.sleep(config.INTERVALO_RECARGA_CONFIG_SEGUNDOS)
                self._recargar_configuracion()

        threading.Thread(target=_loop_recarga, daemon=True, name="recarga-config-readers").start()

    def recargar_ahora(self):
        """Fuerza una recarga inmediata de la configuración de readers/antenas,
        sin esperar al próximo ciclo periódico. Pensado para llamarse justo
        después de un alta/edición/baja hecha desde el panel web."""
        threading.Thread(target=self._recargar_configuracion, daemon=True).start()

    def detener(self):
        self._corriendo = False
        with self._lock:
            conexiones = list(self._conexiones.values())
        for c in conexiones:
            c.detener()

    def estado_actual(self) -> list:
        """Devuelve una lista de dicts con el estado de cada reader conectado,
        útil para mostrar en el panel sin esperar al próximo evento."""
        with self._lock:
            return [
                {
                    "reader_id": rid,
                    "nombre": c.reader_cfg.nombre,
                    "ip": c.reader_cfg.ip_address,
                    "conectado": c.conectado,
                }
                for rid, c in self._conexiones.items()
            ]
