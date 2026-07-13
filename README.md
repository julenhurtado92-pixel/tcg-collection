# Mi Colección TCGs

Versión con stock actual agrupado, umbral de coste unitario medio de 10 EUR, Riftbound tratado como foil por defecto y edición manual desde el detalle de cada elemento.

## Publicación en GitHub Pages

Configura GitHub Pages con:

- Source: Deploy from a branch
- Branch: main
- Folder: /docs

La carpeta `docs/` incluye `.nojekyll` para evitar el build de Jekyll.

## Persistencia desde la web

La web guarda cambios manuales en `localStorage` del navegador. Para hacerlos persistentes en el repositorio:

1. Edita elementos, altas o precios desde la web.
2. Pulsa `Exportar colección` o `Exportar Wish List`.
3. La web descargará el `.json` y el `.js` correspondiente.
4. Sustituye ambos archivos en `docs/data/` dentro del repositorio.

## Regeneración desde Excel

```bash
python scripts/generate_portfolio_data.py --excel "MI COLECCIÓN TCGS.xlsx" --out docs/data --min-unit 10
python scripts/enrich_collection_image_urls.py docs/data/portfolio-data.json
```
