"""Panel de cambios de precio para Google Colab / Jupyter (ipywidgets)."""
import html
import json
import time
import uuid
from datetime import datetime, timezone

import ipywidgets as w
from IPython.display import JSON, Javascript, display

try:  # En Colab el panel se refresca desde el navegador (los hilos no actualizan widgets)
    from google.colab import output as _salida_colab
except ImportError:
    _salida_colab = None

from . import __version__
from .cambios import ACCIONES, Cambio, cargar_catalogo, enviar, restaurar, validar
from .credenciales import conectar, leer_csv
from .seguimiento import estado, version_actual

REGION = "us-east-2"
COLA = "g1-olist-web-cambios.fifo"
URL_SITIO = "https://d1wz0ixjw02i7c.cloudfront.net/"
ESTILO = {"description_width": "110px"}
ETAPAS = [("enviado", "Enviado"), ("publicado", "Publicado"), ("en_sitio", "En el sitio"), ("scrapeado", "Scrapeado")]

CSS = """
<style>
.olcp {font-family: system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif; font-size: 13px; color: inherit;}
.olcp-titulo {font-size: 17px; font-weight: 600;}
.olcp-sub {opacity: .65; font-size: 12px; margin-top: 2px;}
.olcp-seccion {font-size: 11px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; opacity: .6;
               margin: 14px 0 4px 0; padding-bottom: 3px; border-bottom: 1px solid rgba(128,128,128,.25);}
.olcp table {border-collapse: collapse;}
.olcp td, .olcp th {padding: 3px 14px 3px 0; text-align: left; vertical-align: top;}
.olcp th {font-weight: 600; opacity: .7; font-size: 12px;}
.olcp .num {font-variant-numeric: tabular-nums;}
.olcp .ok {color: #1a7f37;} .olcp .aviso {color: #b35900;} .olcp .error {color: #cf222e;} .olcp .gris {opacity: .45;}
</style>
"""


def _html(contenido):
    return f"{CSS}<div class='olcp'>{contenido}</div>"


def _contenido_subido(widget):
    valor = widget.value
    archivo = next(iter(valor.values()), None) if isinstance(valor, dict) else (valor[0] if valor else None)
    return None if archivo is None else bytes(archivo["content"])


def _limpiar_subida(widget):
    try:
        if isinstance(widget.value, dict):
            widget.value.clear()
            widget._counter = 0
        else:
            widget.value = ()
    except Exception:
        pass


class PanelPrecios:
    """Formulario para cambiar precios en los sitios de la competencia y seguir el cambio hasta el scraping."""

    def __init__(self, url_sitio: str = URL_SITIO):
        self.catalogo = cargar_catalogo()
        self.productos = {p["sku"]: p for p in self.catalogo["productos"]}
        self.url_sitio = url_sitio
        self.conexion = None
        self.historial = []  # dicts: cambio, message_id, sku_loja, version_previa, estado
        self._callback = f"olcp_refrescar_{uuid.uuid4().hex[:8]}"
        if _salida_colab is not None:
            _salida_colab.register_callback(self._callback, self._tick)
        self._construir()

    # 1. CONTROLES
    def _construir(self):
        self.w_encabezado = w.HTML(_html(
            "<div class='olcp-titulo'>Precios de la competencia</div>"
            f"<div class='olcp-sub'>Grupo 1 · DMC · Cambios en tiempo real para el scraping · v{__version__}</div>"))
        self.w_archivo = w.FileUpload(accept=".csv", multiple=False, description="Subir CSV", layout=w.Layout(width="140px"))
        self.w_estado_cred = w.HTML(_html("<span class='aviso'>Sin credenciales. Suba el CSV de access keys.</span>"))
        self.w_archivo.observe(self._al_subir, names="value")

        opciones_tienda = [(d["nombre"], t) for t, d in self.catalogo["tiendas"].items()]
        self.w_tienda = w.Dropdown(options=opciones_tienda, description="Tienda", style=ESTILO, layout=w.Layout(width="320px"))
        self.w_producto = w.Dropdown(description="Producto", style=ESTILO, layout=w.Layout(width="560px"))
        self.w_accion = w.ToggleButtons(options=[(v.split(" (")[0], k) for k, v in ACCIONES.items()],
                                        description="Acción", style={**ESTILO, "button_width": "150px"})
        self.w_valor = w.FloatText(value=0, description="Valor", style=ESTILO, layout=w.Layout(width="220px"))
        self.w_ayuda_valor = w.HTML()
        self.w_autor = w.Text(placeholder="Nombre de quien hace el cambio", description="Autor", style=ESTILO,
                              layout=w.Layout(width="320px"))
        self.w_tienda.observe(lambda _: self._actualizar_productos(), names="value")
        self.w_producto.observe(lambda _: self._actualizar_valor(), names="value")
        self.w_accion.observe(lambda _: self._actualizar_valor(), names="value")

        self.b_previa = w.Button(description="Vista previa", icon="eye")
        self.b_publicar = w.Button(description="Publicar", icon="upload", button_style="primary", disabled=True)
        self.b_restaurar = w.Button(description="Restaurar todo", icon="undo", button_style="warning", disabled=True)
        self.b_previa.on_click(lambda _: self._previa())
        self.b_publicar.on_click(lambda _: self._publicar())
        self.b_restaurar.on_click(lambda _: self._restaurar())
        self.w_mensaje = w.HTML()
        self.w_panel = w.HTML()
        self._actualizar_productos()
        self._pintar_panel()

    def _actualizar_productos(self):
        vendidos = self.catalogo["tiendas"][self.w_tienda.value]["productos"]
        self.w_producto.options = [
            (f"{sku} · {self.productos[sku]['nombre']} · {self.productos[sku]['marca']} "
             f"(Olist R$ {self.productos[sku]['precio_olist']:.2f})", sku) for sku in sorted(vendidos)]
        self._actualizar_valor()

    def _actualizar_valor(self):
        accion, sku = self.w_accion.value, self.w_producto.value
        self.w_valor.disabled = accion in ("agotar", "reponer")
        if accion == "precio" and sku:
            self.w_valor.value = round(self.productos[sku]["precio_olist"] * 0.9, 2)
            self.w_ayuda_valor.value = _html("<span class='gris'>R$. Sugerido: 10% bajo el precio Olist.</span>")
        elif accion == "descuento":
            self.w_valor.value = 25
            self.w_ayuda_valor.value = _html("<span class='gris'>% sobre el precio de lista de la tienda.</span>")
        else:
            self.w_ayuda_valor.value = ""

    # 2. CREDENCIALES
    def _al_subir(self, _):
        contenido = _contenido_subido(self.w_archivo)
        if contenido is None:
            return
        try:
            self.conexion = conectar(leer_csv(contenido), REGION, COLA)
            usuario = self.conexion.identidad.rsplit("/", 1)[-1]
            self.w_estado_cred.value = _html(f"<span class='ok'>Conectado como {html.escape(usuario)}.</span>")
        except ValueError as error:
            self.conexion = None
            self.w_estado_cred.value = _html(f"<span class='error'>{html.escape(str(error))}</span>")
        finally:
            del contenido
            _limpiar_subida(self.w_archivo)
        self.b_publicar.disabled = self.b_restaurar.disabled = self.conexion is None

    # 3. ACCIONES
    def _cambio(self):
        valor = None if self.w_accion.value in ("agotar", "reponer") else float(self.w_valor.value)
        return Cambio(tienda=self.w_tienda.value, sku=self.w_producto.value, accion=self.w_accion.value,
                      valor=valor, autor=self.w_autor.value.strip())

    def _mostrar_validacion(self, cambio):
        errores, avisos = validar(cambio, self.catalogo)
        partes = [f"<div class='error'>{html.escape(e)}</div>" for e in errores]
        partes += [f"<div class='aviso'>{html.escape(a)}</div>" for a in avisos]
        return errores, "".join(partes)

    def _previa(self):
        cambio = self._cambio()
        errores, texto = self._mostrar_validacion(cambio)
        mensaje = html.escape(json.dumps(cambio.mensaje(), ensure_ascii=False, indent=1))
        self.w_mensaje.value = _html(f"{texto}<div class='olcp-seccion'>Mensaje a enviar</div><pre>{mensaje}</pre>")

    def _publicar(self, cambio=None):
        cambio = cambio or self._cambio()
        errores, texto = self._mostrar_validacion(cambio)
        if errores:
            self.w_mensaje.value = _html(texto)
            return
        previo = version_actual(self.url_sitio)
        message_id = enviar(self.conexion, cambio)
        sku_loja = self.catalogo["tiendas"].get(cambio.tienda, {}).get("productos", {}).get(cambio.sku)
        self.historial.insert(0, {"cambio": cambio, "message_id": message_id, "sku_loja": sku_loja,
                                  "version_previa": previo, "estado": {"etapas": {"enviado": 0}}, "inicio": time.time()})
        self.w_mensaje.value = _html(f"{texto}<span class='ok'>Cambio {cambio.cambio_id} enviado.</span>")
        self._pintar_panel()

    def _restaurar(self):
        self._publicar(restaurar(self.w_autor.value.strip()))

    # 4. SEGUIMIENTO
    def _actualizar_estados(self):
        for h in self.historial:
            if self._terminado(h):
                continue
            h["estado"] = estado(h["cambio"], self.url_sitio, h["sku_loja"], h["version_previa"])

    def _pintar_panel(self):
        if not self.historial:
            self.w_panel.value = _html("<div class='olcp-seccion'>Cambios de esta sesión</div>"
                                       "<span class='gris'>Aún no hay cambios.</span>")
            return
        filas = []
        for h in self.historial[:15]:
            c, et = h["cambio"], h["estado"]["etapas"]
            tienda = self.catalogo["tiendas"].get(c.tienda, {}).get("nombre", "Todas")
            detalle = "Restaurar precios del día" if c.accion == "restaurar" else \
                f"{c.sku} · {ACCIONES[c.accion].split(' (')[0]}" + (f" {c.valor:g}" if c.valor is not None else "")
            celdas = []
            for clave, _ in ETAPAS:
                if clave in et:
                    seg = et[clave]
                    celdas.append(f"<td class='ok num'>✓{'' if seg in (None, 0) else f' {seg} s'}</td>")
                else:
                    celdas.append("<td class='gris'>…</td>")
            if "rechazado" in h["estado"]:
                reglas = f"<span class='error'>rechazado: {html.escape(h['estado']['rechazado'])}</span>"
            else:
                reglas = "" if "reglas_ok" not in et else ("<span class='ok'>reglas OK</span>" if et["reglas_ok"]
                                                             else "<span class='aviso'>revisar reglas</span>")
            filas.append(f"<tr><td class='num'>{c.cambio_id}</td><td>{tienda}</td><td>{html.escape(detalle)}</td>"
                         f"{''.join(celdas)}<td>{reglas}</td></tr>")
        cabecera = "".join(f"<th>{n}</th>" for _, n in ETAPAS)
        self.w_panel.value = _html(
            "<div class='olcp-seccion'>Cambios de esta sesión</div>"
            f"<table><tr><th>Cambio</th><th>Tienda</th><th>Detalle</th>{cabecera}<th></th></tr>{''.join(filas)}</table>")

    @staticmethod
    def _terminado(h):
        return ("scrapeado" in h["estado"]["etapas"] or "rechazado" in h["estado"]
                or time.time() - h["inicio"] > 900)

    def _pendientes(self):
        return any(not self._terminado(h) for h in self.historial)

    def _tick(self):
        try:
            if self.conexion is not None and self._pendientes():
                self._actualizar_estados()
                self._pintar_panel()
        except Exception as error:
            self.w_mensaje.value = _html(f"<div class='error'>Error del panel: {html.escape(str(error))}</div>")
        return JSON({"espera": 4000 if self._pendientes() else 8000})

    def mostrar(self):
        display(w.VBox([
            self.w_encabezado,
            w.HTML(_html("<div class='olcp-seccion'>Credenciales</div>")), w.HBox([self.w_archivo, self.w_estado_cred]),
            w.HTML(_html("<div class='olcp-seccion'>Cambio</div>")),
            self.w_tienda, self.w_producto, self.w_accion, w.HBox([self.w_valor, self.w_ayuda_valor]), self.w_autor,
            w.HBox([self.b_previa, self.b_publicar, self.b_restaurar]), self.w_mensaje, self.w_panel]))
        if _salida_colab is not None:
            display(Javascript(f"""
              (async () => {{
                while (true) {{
                  let espera = 8000;
                  try {{
                    const r = await google.colab.kernel.invokeFunction('{self._callback}', [], {{}});
                    espera = r.data['application/json'].espera;
                  }} catch (e) {{}}
                  await new Promise(ok => setTimeout(ok, espera));
                }}
              }})();"""))
        else:
            boton = w.Button(description="Actualizar estado", icon="refresh")
            boton.on_click(lambda _: self._tick() and None)
            display(boton)
