# Precios de la competencia (Olist) - Grupo 1 DMC

Panel para Google Colab que cambia en tiempo real los precios de cuatro tiendas simuladas de la competencia de
Olist (Mercado Abierto, Selva, Compree y Ridley). Cada cambio se publica en el sitio, lo lee el scraper del
proyecto y aparece en Power BI.

```
Colab ──► SQS (FIFO) ──► Lambda publicadora ──► sitio en S3 + CloudFront
                                                  │ aviso de S3
                                                  ▼
                                    Lambda scraper ──► lakehouse (web/landing) ──► Athena / Power BI
```

## Uso en Colab

```python
%pip install -q git+https://github.com/favc0608/Scraping_Competencia.git@v1.0.0
from olist_competencia import PanelPrecios
PanelPrecios().mostrar()
```

1. Suba el CSV de access keys del usuario de Colab (se lee en memoria; no se guarda).
2. Elija tienda, producto y acción: nuevo precio, descuento, agotar o reponer.
3. **Vista previa** muestra el mensaje y avisa si el precio quedaría fuera del rango plausible (50%-150% del
   precio Olist), que el scraper marca como sospechoso.
4. **Publicar** envía el cambio. El panel sigue cada etapa: enviado, publicado, visible en el sitio y scrapeado.
5. **Restaurar todo** vuelve a los precios calculados del día.

Los cambios valen hasta la publicación diaria siguiente (05:00, hora de Lima), que recalcula los precios.

## Contenido

| Archivo | Para qué |
|---|---|
| `olist_competencia/interfaz.py` | Panel (ipywidgets) |
| `olist_competencia/cambios.py` | Validación y envío a la cola |
| `olist_competencia/seguimiento.py` | Estado de cada cambio |
| `olist_competencia/credenciales.py` | Lectura del CSV de access keys en memoria |
| `olist_competencia/datos/catalogo.json` | Productos y surtido de cada tienda (datos simulados) |
| `notebooks/precios_competencia_g1.ipynb` | Notebook listo para abrir en Colab |

Pruebas: `python -m unittest discover -s tests`.
