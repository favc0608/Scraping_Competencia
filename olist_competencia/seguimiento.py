"""Seguimiento de un cambio: enviado -> publicado -> visible en el sitio -> scrapeado.

Solo lee archivos públicos del sitio: no necesita permisos de AWS más allá de enviar a la cola.
  _estado/publicacion.json  última publicación y resultado de cada cambio procesado
  _estado/scraping.json     última corrida del scraper y si sus reglas quedaron OK
"""
import json
import re
import time
from datetime import datetime
from urllib.request import Request, urlopen

AGENTE = "g1-olist-colab/1.0"


def _leer(url: str):
    try:
        req = Request(f"{url}?t={int(time.time())}", headers={"User-Agent": AGENTE})
        with urlopen(req, timeout=10) as r:
            return r.read().decode("utf-8")
    except Exception:
        return None


def _json(url: str) -> dict:
    texto = _leer(url)
    try:
        return json.loads(texto) if texto else {}
    except ValueError:
        return {}


def version_en_sitio(url_sitio: str, tienda: str, sku_loja: str):
    html = _leer(f"{url_sitio.rstrip('/')}/{tienda}/produto/{sku_loja}.html")
    m = re.search(r'<meta name="g1-version" content="([^"]+)"', html or "")
    return m.group(1) if m else None


def _segundos(desde_iso, hasta_iso):
    try:
        return max(0, int((datetime.fromisoformat(hasta_iso) - datetime.fromisoformat(desde_iso)).total_seconds()))
    except (TypeError, ValueError):
        return None


def version_actual(url_sitio: str):
    return _json(f"{url_sitio.rstrip('/')}/_estado/publicacion.json").get("version")


def estado(cambio, url_sitio: str, sku_loja: str = None, version_previa: str = None) -> dict:
    """Etapas cumplidas del cambio, con su latencia en segundos desde el envío."""
    base = url_sitio.rstrip("/")
    pub = _json(f"{base}/_estado/publicacion.json")
    scr = _json(f"{base}/_estado/scraping.json")
    etapas, motivo = {"enviado": 0}, ""
    procesado = next((p for p in pub.get("procesados", []) if p.get("cambio_id") == cambio.cambio_id), None)
    publicado = procesado is not None or (pub.get("version") not in (None, version_previa)
                                          and (pub.get("publicado_en") or "") >= (cambio.enviado_en or ""))
    if procesado and procesado.get("estado") == "rechazado":
        motivo = procesado.get("motivo") or "rechazado"
        return {"etapas": etapas, "rechazado": motivo, "version": pub.get("version")}
    if publicado:
        etapas["publicado"] = _segundos(cambio.enviado_en, pub.get("publicado_en"))
        if sku_loja is None or version_en_sitio(base, cambio.tienda, sku_loja) == pub.get("version"):
            etapas["en_sitio"] = None
        if scr.get("version") == pub.get("version") and (not cambio.tienda or cambio.tienda in scr.get("tiendas", [])):
            etapas["scrapeado"] = _segundos(cambio.enviado_en, scr.get("terminado_en") or scr.get("capturado_en"))
            etapas["reglas_ok"] = bool(scr.get("ok"))
    return {"etapas": etapas, "version": pub.get("version"), "cambios_del_dia": pub.get("cambios")}
