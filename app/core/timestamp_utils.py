"""
timestamp_utils.py — Conversión de timestamps LLRP (microsegundos UTC desde
epoch) a objetos datetime usables por pyodbc/SQL Server.
"""

from datetime import datetime, timezone
from typing import Optional


def timestamp_llrp_a_datetime(tag: dict) -> datetime:
    """
    Convierte el campo LastSeenTimestampUTC de un tag report LLRP
    (microsegundos desde epoch UTC) a un datetime con timezone UTC.
    Si no está presente, devuelve el momento actual como fallback.
    """
    ts = tag.get("LastSeenTimestampUTC")
    if isinstance(ts, dict):
        ts = ts.get("Microseconds")

    if ts:
        try:
            return datetime.fromtimestamp(ts / 1_000_000.0, tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            pass

    return datetime.now(timezone.utc)
