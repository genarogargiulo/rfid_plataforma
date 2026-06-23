"""
epc_decoder.py — Utilidades para decodificar el EPC crudo que entrega el
reader (bytes / hex) a representaciones útiles para guardar y explotar:
  - Hex (siempre disponible, formato canónico para joins/filtros)
  - ASCII (si el contenido del tag fue programado como texto legible,
    como se observó en las pruebas de campo con los tags FPT)

No se asume un esquema EPC estándar (SGTIN, etc.) porque las pruebas de
campo mostraron tags con contenido de texto plano, no codificación GS1
estándar. Si en el futuro se usan tags con esquema EPC estándar, se puede
extender esta función sin tocar el resto de la aplicación.
"""

from typing import Optional, Tuple


def extraer_epc_crudo(tag: dict):
    """Extrae el valor de EPC de un tag report LLRP, sin decodificar."""
    epc = tag.get("EPC-96") or tag.get("EPCData") or tag.get("EPC")
    if isinstance(epc, dict) and "EPC" in epc:
        epc = epc["EPC"]
    return epc


def decodificar_epc(tag: dict) -> Tuple[str, Optional[str]]:
    """
    Devuelve (epc_hex, epc_ascii_o_None).

    epc_hex: representación hexadecimal en mayúsculas, siempre presente.
    epc_ascii: si los bytes decodifican a texto ASCII imprimible, se
               devuelve ese texto; si no, None (se guarda solo el hex).
    """
    crudo = extraer_epc_crudo(tag)

    if crudo is None:
        return "DESCONOCIDO", None

    if isinstance(crudo, bytes):
        epc_hex = crudo.hex().upper()
        epc_ascii = _intentar_decodificar_ascii(crudo)
        return epc_hex, epc_ascii

    # Si ya viene como string (algunas versiones de sllurp lo entregan así)
    texto = str(crudo)
    try:
        crudo_bytes = bytes.fromhex(texto)
        epc_ascii = _intentar_decodificar_ascii(crudo_bytes)
        return texto.upper(), epc_ascii
    except ValueError:
        # No es hex válido; se guarda tal cual en el campo hex como fallback
        return texto, None


def _intentar_decodificar_ascii(data: bytes) -> Optional[str]:
    """Intenta decodificar bytes como ASCII imprimible. Si contiene bytes
    no imprimibles o no es ASCII válido, devuelve None."""
    try:
        texto = data.decode("ascii")
    except UnicodeDecodeError:
        return None

    # Permitir el padding con \x00 al final (común en tags), recortarlo
    texto = texto.rstrip("\x00")

    if not texto:
        return None

    # Validar que sea razonablemente "texto" (imprimible), no basura binaria
    # que por casualidad cayó en rango ASCII.
    imprimibles = sum(1 for c in texto if c.isprintable())
    if imprimibles / len(texto) < 0.9:
        return None

    return texto
