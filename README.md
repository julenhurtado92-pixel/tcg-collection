# Mi Colección TCGs - refactor 20€/unidad

Paquete preparado para publicar en GitHub Pages desde `docs/`.

La regla principal queda centralizada y documentada:

> La web solo muestra filas con `Tipo Operación = Compra` y `Unit Price >= 20€`.

El Excel sigue siendo la fuente completa. No se eliminan compras, ventas ni cancelados del archivo original; el filtro se aplica únicamente al generar `portfolio-data.json` y `portfolio-data.js`.

## Estructura

```text
docs/
  data/
    portfolio-data.js
    portfolio-data.json
  app.js
  index.html
  styles.css
scripts/
  generate_portfolio_data.py
  enrich_scryfall_images.py
README.md
```

## Regenerar datos desde Excel

Coloca `MI COLECCIÓN TCGS.xlsx` en la raíz del repositorio y ejecuta:

```bash
python scripts/generate_portfolio_data.py --excel "MI COLECCIÓN TCGS.xlsx" --out docs/data --min-unit 20
```

El generador deja el umbral dentro de `metadata.minUnitPurchaseValue`, para que la web también pueda validarlo como segunda barrera de seguridad.

## Enriquecer imágenes de Scryfall opcionalmente

Después de generar el JSON, puedes resolver imágenes MTG y guardarlas en los propios archivos de datos:

```bash
python scripts/enrich_scryfall_images.py docs/data/portfolio-data.json
```

Esto actualiza tanto `docs/data/portfolio-data.json` como `docs/data/portfolio-data.js`. Las filas no MTG quedan marcadas como `not_applicable`.

## Publicación en GitHub Pages

Configura GitHub Pages para publicar desde la carpeta `docs` de la rama principal. El HTML carga los datos con rutas relativas:

```html
<link rel="stylesheet" href="./styles.css" />
<script src="./data/portfolio-data.js"></script>
<script src="./app.js"></script>
```

## Resultado de esta generación

- Filas fuente leídas del Excel: 3.857
- Filas de compra totales: 3.287
- Filas visibles en web con `Unit Price >= 20€`: 276
- Filas de compra ocultas por estar por debajo del umbral: 3.011
