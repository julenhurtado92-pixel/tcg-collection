# Actualización de precios con Cardmarket Data Tables

Esta versión añade un pipeline para consultar precios de mercado usando las tablas públicas de Cardmarket:

- `Product Catalog`: catálogo de productos, singles, non-singles y accesorios.
- `Price Guides`: precios diarios agregados.

No se descargan páginas de producto una por una. El proceso descarga los JSON publicados por Cardmarket, cruza cada elemento de la colección por TCG, nombre, edición, variante y tipo aproximado, y guarda el resultado en los JSON de la web.

## Archivos añadidos

```text
scripts/update_cardmarket_prices.py
.github/workflows/update-cardmarket-prices.yml
docs/data/market-prices.json
docs/data/market-prices.js
docs/data/cardmarket-overrides.json
docs/data/cardmarket-matching-report.csv
docs/data/cardmarket-matching-report.json
```

## Uso local

Desde la raíz del repositorio:

```bash
python scripts/update_cardmarket_prices.py \
  --portfolio docs/data/portfolio-data.json \
  --wishlist docs/data/wishlist-data.json \
  --overrides docs/data/cardmarket-overrides.json \
  --out docs/data \
  --cache .cache/cardmarket \
  --update-portfolio \
  --update-wishlist \
  --force-download
```

El comando genera o actualiza:

```text
docs/data/market-prices.json
docs/data/market-prices.js
docs/data/portfolio-data.json
docs/data/portfolio-data.js
docs/data/wishlist-data.json
docs/data/wishlist-data.js
docs/data/cardmarket-matching-report.csv
docs/data/cardmarket-matching-report.json
```

Después haz commit y push:

```bash
git add docs/data scripts/update_cardmarket_prices.py .github/workflows/update-cardmarket-prices.yml README_CARDMARKET.md
git commit -m "Actualizar precios Cardmarket"
git push
```

## Uso desde GitHub Actions

1. Sube esta versión al repositorio.
2. Entra en GitHub > `Actions`.
3. Abre el workflow `Actualizar precios Cardmarket`.
4. Pulsa `Run workflow`.
5. Deja `min_confidence` en `72` al principio.
6. Ejecuta.
7. El workflow descargará las tablas, actualizará los JSON y hará commit automáticamente.

## Revisión de coincidencias dudosas

Después de ejecutar el script, revisa:

```text
docs/data/cardmarket-matching-report.csv
```

Estados posibles:

- `resolved`: coincidencia automática válida.
- `ambiguous`: hay varios candidatos parecidos.
- `unmatched`: no se ha encontrado match suficientemente fiable.
- `manual`: precio o producto fijado manualmente.

Para resolver un caso dudoso, localiza el `itemId` en el CSV y edita:

```json
{
  "items": {
    "stock-magic-the-gathering-city-of-traitors-exodus-japones-nonfoil": {
      "idProduct": 123456,
      "notes": "Producto confirmado manualmente en Cardmarket"
    }
  },
  "wishlistItems": {}
}
```

Luego vuelve a ejecutar el script. Los overrides tienen prioridad sobre el matching automático.

## Uso desde la web

La sección `Consulta de precios Cardmarket` muestra:

- precio unitario de mercado,
- valor total de mercado,
- diferencia contra coste,
- estado del matching,
- enlace de búsqueda en Cardmarket cuando existe candidato.

También puedes usar `Importar market-prices.json` para cargar un archivo generado localmente sin subirlo todavía al repositorio. Una vez importado, usa `Exportar datos` o `Exportar colección` para descargar `portfolio-data.json` y `portfolio-data.js` ya enriquecidos con precios.

## Limitaciones conocidas

Cardmarket publica datos agregados diarios, no listings filtrados por vendedor, idioma, condición o país. Por tanto, el precio debe tratarse como referencia de mercado. En cartas con muchas reimpresiones, versiones alternativas o nombres idénticos, revisa los estados `ambiguous` y usa `cardmarket-overrides.json`.
