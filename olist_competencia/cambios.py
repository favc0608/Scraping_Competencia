"""Cambios de precio: catálogo, validación y envío a la cola FIFO del publicador."""
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from importlib import resources

ACCIONES = {"precio": "Nuevo precio (R$)", "descuento": "Descuento sobre el precio de lista (%)",
            "agotar": "Marcar como agotado", "reponer": "Reponer stock"}
GRUPO = "cambios-competencia"  # un solo grupo FIFO: los cambios se aplican en orden


def cargar_catalogo() -> dict:
    texto = resources.files("olist_competencia").joinpath("datos/catalogo.json").read_text(encoding="utf-8")
    return json.loads(texto)


@dataclass
class Cambio:
    tienda: str
    sku: str
    accion: str
    valor: float = None
    autor: str = ""
    cambio_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    enviado_en: str = None

    def mensaje(self) -> dict:
        datos = {k: v for k, v in asdict(self).items() if v is not None and v != ""}
        if self.accion in ("agotar", "reponer", "restaurar"):
            datos.pop("valor", None)
        return datos


def restaurar(autor: str = "") -> Cambio:
    return Cambio(tienda="", sku="", accion="restaurar", autor=autor)


def validar(cambio: Cambio, catalogo: dict) -> tuple:
    """Devuelve (errores, avisos). Los errores impiden enviar; los avisos solo informan."""
    errores, avisos = [], []
    if cambio.accion == "restaurar":
        return errores, avisos
    tienda = catalogo["tiendas"].get(cambio.tienda)
    if not tienda:
        errores.append("Seleccione una tienda.")
        return errores, avisos
    if cambio.sku not in tienda["productos"]:
        errores.append("La tienda no vende ese producto.")
    if cambio.accion not in ACCIONES:
        errores.append("Acción no válida.")
    if cambio.accion == "precio":
        if not cambio.valor or cambio.valor <= 0:
            errores.append("Ingrese un precio mayor que cero.")
        else:
            olist = next(p["precio_olist"] for p in catalogo["productos"] if p["sku"] == cambio.sku)
            ratio = cambio.valor / olist
            if not 0.5 <= ratio <= 1.5:
                avisos.append(f"El precio es {ratio:.0%} del precio Olist (R$ {olist:.2f}). "
                              "El scraper lo marcará como sospechoso (regla R9).")
    if cambio.accion == "descuento" and not (cambio.valor and 1 <= cambio.valor <= 90):
        errores.append("El descuento debe estar entre 1 y 90%.")
    return errores, avisos


def enviar(conexion, cambio: Cambio) -> str:
    """Envía el cambio a la cola FIFO. Devuelve el MessageId."""
    cambio.enviado_en = datetime.now(timezone.utc).isoformat()
    r = conexion.session.client("sqs").send_message(
        QueueUrl=conexion.url_cola, MessageBody=json.dumps(cambio.mensaje(), ensure_ascii=False),
        MessageGroupId=GRUPO, MessageDeduplicationId=cambio.cambio_id)
    return r["MessageId"]
