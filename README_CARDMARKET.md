# Actualización de precios Cardmarket V7 scrape

Esta versión elimina la dependencia de una API key externa para los precios filtrados. El flujo recomendado queda así:

1. **Data Tables** localiza el `idProduct` correcto.
2. El matching se hace con control estricto de **nombre + edición + variante**.
3. El script abre la página pública del producto en Cardmarket.
4. Se aplican filtros de página para **idioma** y **condición mínima** cuando están disponibles.
5. Los listings extraídos se vuelven a filtrar localmente por:
   - idioma del item,
   - condición `NM` o superior,
   - vendedores de Europa,
   - exclusión de Reino Unido,
   - variante foil/non-foil cuando el listing la expone.
6. El precio recomendado es la **media de las 5 ofertas válidas más baratas**.
7. Si no hay 5 ofertas válidas, el item queda como `insufficient_sample` / `Sin muestra suficiente` y no se incluye en la valoración de mercado.

El modo `datatables` sigue disponible como respaldo estable y no hace scraping de listings.

## Archivos principales

```text
scripts/update_cardmarket_prices.py
.github/workflows/update-cardmarket-prices.yml
docs/app.js
docs/data/market-prices.json
docs/data/market-prices.js
docs/data/cardmarket-overrides.json
docs/data/cardmarket-matching-report.csv
docs/data/cardmarket-matching-report.json
```

## GitHub Actions

El workflow `Actualizar precios Cardmarket` ya queda configurado por defecto con:

```text
pricing_mode = scrape
listing_language = auto
listing_condition = nm
listing_sample_size = 5
```

No necesitas `CARDMARKET_LIVE_API_KEY` para V7.

Opcionalmente puedes crear este secreto si tu sesión local de Cardmarket ayuda a evitar páginas incompletas o bloqueos:

```text
CARDMARKET_COOKIE
```

El workflow lo pasa como variable de entorno, pero no lo escribe en JSON, CSV ni logs. Déjalo sin configurar si no quieres usar cookies.

## Uso local V7 scrape

Desde la raíz del repositorio:

```bash
python scripts/update_cardmarket_prices.py \
  --portfolio docs/data/portfolio-data.json \
  --wishlist docs/data/wishlist-data.json \
  --overrides docs/data/cardmarket-overrides.json \
  --out docs/data \
  --cache .cache/cardmarket \
  --scrape-cache .cache/cardmarket-scrape \
  --pricing-mode scrape \
  --listing-language auto \
  --listing-condition nm \
  --listing-sample-size 5 \
  --strict-matching \
  --update-portfolio \
  --update-wishlist \
  --force-download \
  --force-scrape-download
```

Con cookie opcional:

```bash
export CARDMARKET_COOKIE='tu_cookie_completa'

python scripts/update_cardmarket_prices.py \
  --portfolio docs/data/portfolio-data.json \
  --wishlist docs/data/wishlist-data.json \
  --overrides docs/data/cardmarket-overrides.json \
  --out docs/data \
  --cache .cache/cardmarket \
  --scrape-cache .cache/cardmarket-scrape \
  --pricing-mode scrape \
  --listing-language auto \
  --listing-condition nm \
  --listing-sample-size 5 \
  --strict-matching \
  --update-portfolio \
  --update-wishlist
```

## Parámetros clave

- `--pricing-mode scrape`: activa V7, Data Tables + scraping de listings.
- `--pricing-mode datatables`: usa solo Price Guides diarios.
- `--pricing-mode hybrid`: conserva el modo legacy de proveedor live externo con API key.
- `--listing-language auto`: usa el idioma de cada item de la colección.
- `--listing-condition nm`: condición mínima NM; acepta NM y MT.
- `--listing-sample-size 5`: media de las 5 ofertas válidas más baratas.
- `--exclude-uk` / `--no-exclude-uk`: excluye o permite vendedores de Reino Unido.
- `--require-europe` / `--no-require-europe`: exige país europeo conocido o permite cualquier país.
- `--scrape-require-language` / `--no-scrape-require-language`: exige que cada listing exponga idioma reconocible.
- `--scrape-require-condition` / `--no-scrape-require-condition`: exige que cada listing exponga condición reconocible.
- `--max-scrape-items N`: limita el número de items scrapeados para pruebas.
- `--debug-scrape-html`: guarda HTML de bloqueo/challenge en caché para depuración.

## Estados relevantes

```text
resolved                Match y muestra suficiente.
insufficient_sample     idProduct resuelto, pero menos de 5 listings válidos.
unsupported_language    Idioma del item no mapeable.
scrape_blocked          La página devolvió bloqueo, challenge o respuesta no usable.
scrape_error            Error general descargando o parseando la página.
scrape_no_product_page  No se pudo localizar una página de producto scrapeable.
scrape_skipped_limit    Omitido por --max-scrape-items.
ambiguous               Hay varios candidatos similares.
unmatched               No hay match seguro.
manual                  Precio manual fijado en la web.
```

## Salidas generadas

```text
docs/data/market-prices.json
docs/data/market-prices.js
docs/data/cardmarket-matching-report.csv
docs/data/cardmarket-matching-report.json
```

El CSV de reporte incluye columnas específicas de V7:

```text
source
pricingMode
listingLanguage
listingCondition
scrapeSampleSize
scrapeValidListings
scrapeRawListings
scrapeLow
scrapeProductUrl
scrapeStatus
scrapeReason
fallbackPriceGuideUnit
```

También se mantienen columnas `live*` como alias de compatibilidad para pantallas/reportes existentes.

## Overrides manuales

Los overrides siguen igual. Si un producto queda `ambiguous` o `unmatched`, rellena el `idProduct` confirmado:

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

En modo `scrape`, el override solo fija el producto. El precio final seguirá saliendo de listings filtrados.

## Modo seguro sin scraping

Para seguir usando solo Data Tables:

```bash
python scripts/update_cardmarket_prices.py \
  --portfolio docs/data/portfolio-data.json \
  --wishlist docs/data/wishlist-data.json \
  --overrides docs/data/cardmarket-overrides.json \
  --out docs/data \
  --cache .cache/cardmarket \
  --pricing-mode datatables \
  --update-portfolio \
  --update-wishlist
```
