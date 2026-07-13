# Mi Colección TCGs - Stock actual

Web estática para GitHub Pages con inventario TCG agrupado, conciliado contra ventas y preparado para altas locales, Wish List y análisis de gasto.

## Cambios principales

- El Excel sigue siendo la fuente completa.
- Las entradas se normalizan antes de publicar:
  - `[Playset]` con `Quantity = 1` se convierte en 4 unidades y se elimina la coletilla del nombre.
  - Compras y ventas se concilian para calcular stock actual.
  - Los elementos se agrupan por `TCG + nombre + edición + idioma + variante Foil/Non-foil`.
  - El coste unitario publicado es el coste total real repartido entre unidades.
  - El filtro de publicación se aplica después de la agrupación y conciliación.
- La interfaz ya no muestra paneles técnicos de pipeline, reglas o resolución de imágenes.
- La navegación se hace mediante menú hamburguesa.
- Se añaden secciones de Colección, Gráficos, Wish List y Alta manual.
- Las altas manuales y la Wish List persisten en `localStorage` y pueden exportarse como JSON.

## Regenerar datos desde Excel

```bash
python scripts/generate_portfolio_data.py --excel "MI COLECCIÓN TCGS.xlsx" --out docs/data --min-unit 20
python scripts/enrich_collection_image_urls.py docs/data/portfolio-data.json
```

## Archivos de datos

- `docs/data/portfolio-data.json`: stock actual visible y datos analíticos.
- `docs/data/portfolio-data.js`: equivalente JS para carga estática.
- `docs/data/wishlist-data.json`: Wish List base.
- `docs/data/wishlist-data.js`: equivalente JS para carga estática.
- `docs/data/stock-reconciliation-report.json`: reporte de ventas conciliadas o dudosas.
- `docs/data/stock-reconciliation-report.csv`: mismo reporte en CSV.
- `docs/data/image-resolution-report.json`: reporte de URLs de imagen.
- `docs/data/image-resolution-report.csv`: mismo reporte en CSV.

## Persistencia desde la web

GitHub Pages no puede escribir directamente en el repositorio desde el navegador. Por eso la primera implementación usa:

1. `localStorage` para que los datos añadidos reaparezcan en el mismo navegador.
2. Botones de exportación para descargar `portfolio-data.json` o `wishlist-data.json` actualizados.

Para que los cambios exportados queden en el repo, reemplaza manualmente los JSON dentro de `docs/data/`.

## Precios de mercado

La interfaz incluye botones de actualización de precio a demanda. En esta versión quedan preparados como punto de entrada visual; el conector/scraper se añadirá en la siguiente fase.
