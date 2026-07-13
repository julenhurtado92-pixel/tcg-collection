# Mi Coleccion TCGs - refactor 20 EUR/unidad + imagenes

Paquete preparado para publicar en GitHub Pages desde `docs/`.

La regla principal queda centralizada y documentada:

> La web solo muestra filas con `Tipo Operacion = Compra` y `Unit Price >= 20 EUR`.

El Excel sigue siendo la fuente completa. No se eliminan compras, ventas ni cancelados del archivo original; el filtro se aplica unicamente al generar `portfolio-data.json` y `portfolio-data.js`.

## Estructura

```text
docs/
  data/
    portfolio-data.js
    portfolio-data.json
    image-resolution-report.csv
    image-resolution-report.json
  app.js
  index.html
  styles.css
scripts/
  generate_portfolio_data.py
  enrich_collection_image_urls.py
  enrich_scryfall_images.py
README.md
```

## Regenerar datos desde Excel

Coloca `MI COLECCION TCGS.xlsx` en la raiz del repositorio y ejecuta:

```bash
python scripts/generate_portfolio_data.py --excel "MI COLECCION TCGS.xlsx" --out docs/data --min-unit 20
```

El generador deja el umbral dentro de `metadata.minUnitPurchaseValue`, para que la web tambien pueda validarlo como segunda barrera de seguridad.

## Enriquecer imagenes

Despues de generar el JSON, ejecuta:

```bash
python scripts/enrich_collection_image_urls.py docs/data/portfolio-data.json
```

Este enriquecedor deja URLs persistidas en el JSON/JS para:

- MTG singles: endpoints de imagen de Scryfall por nombre exacto y, cuando hay mapeo fiable, por set.
- Riftbound singles: endpoints de imagen de Scrydex por codigo de carta.
- One Piece singles: endpoints de imagen de OnePieceDB por codigo de carta.
- Sellado/accesorios/productos: mapeos manuales a imagenes de Riot, Wizards, Ultra PRO o fuente alternativa documentada.

Tambien genera:

- `docs/data/image-resolution-report.json`
- `docs/data/image-resolution-report.csv`

## Resultado de esta generacion

- Filas fuente leidas del Excel: 3.857
- Filas de compra totales: 3.287
- Filas visibles en web con `Unit Price >= 20 EUR`: 276
- Filas de compra ocultas por estar por debajo del umbral: 3.011
- Imagenes resueltas en el dataset visible: 276 / 276
- Imagenes pendientes: 0

## Publicacion en GitHub Pages

Configura GitHub Pages para publicar desde la carpeta `docs` de la rama principal. El HTML carga los datos con rutas relativas:

```html
<link rel="stylesheet" href="./styles.css" />
<script src="./data/portfolio-data.js"></script>
<script src="./app.js"></script>
```
