# Actualización de precios Cardmarket V7.1 scrape

V7.1 mantiene la idea de V7, pero corrige el cuello de botella detectado en los logs: las Data Tables de Cardmarket traen `idExpansion`, pero en muchos productos no traen `expansionName`, así que el matching estricto acababa en `edicion_no_confirmada`.

El flujo actual queda así:

1. **Data Tables** cargan catálogo y Price Guides diarios.
2. Para **MTG singles**, Scryfall se usa como apoyo para obtener el `cardmarket_id` exacto de la impresión cuando está disponible.
3. Si Scryfall no resuelve, se usa el matching Data Tables normal.
4. El script abre la página pública del producto en Cardmarket y aplica idioma + condición mínima cuando la página lo permite.
5. Los listings extraídos se filtran localmente por:
   - idioma del item,
   - condición `NM` o superior,
   - vendedores de Europa,
   - exclusión de Reino Unido,
   - variante foil/non-foil cuando el listing la expone.
6. El precio recomendado es la **media de las 5 ofertas válidas más baratas**.
7. Si el scraping funciona pero no hay 5 ofertas válidas, el item queda como `insufficient_sample` / `Sin muestra suficiente` y no se valora con fallback.
8. Si Cardmarket bloquea técnicamente el scraping (`403`, challenge, página no usable), V7.1 conserva el precio de Data Tables como fallback transparente para no dejar la colección a cero.

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

El workflow `Actualizar precios Cardmarket` queda configurado por defecto con:

```text
pricing_mode = scrape
listing_language = auto
listing_condition = nm
listing_sample_size = 5
scryfall_cardmarket_match = true
scrape_fallback_to_priceguide = true
```

No necesitas `CARDMARKET_LIVE_API_KEY` para V7.1.

Opcionalmente puedes crear este secreto si tu sesión local de Cardmarket ayuda a evitar páginas incompletas o bloqueos:

```text
CARDMARKET_COOKIE
```

El workflow lo pasa como variable de entorno, pero no lo escribe en JSON, CSV ni logs. Déjalo sin configurar al principio. Aunque haya cookie, Cardmarket puede bloquear peticiones desde GitHub Actions; por eso V7.1 incluye fallback a Data Tables cuando el problema es técnico.

## Uso local V7.1 scrape

Desde la raíz del repositorio:

```bash
python scripts/update_cardmarket_prices.py \
  --portfolio docs/data/portfolio-data.json \
  --wishlist docs/data/wishlist-data.json \
  --overrides docs/data/cardmarket-overrides.json \
  --out docs/data \
  --cache .cache/cardmarket \
  --scrape-cache .cache/cardmarket-scrape \
  --scryfall-cache .cache/scryfall-cardmarket \
  --pricing-mode scrape \
  --listing-language auto \
  --listing-condition nm \
  --listing-sample-size 5 \
  --scryfall-cardmarket-match \
  --scrape-fallback-to-priceguide \
  --strict-matching \
  --update-portfolio \
  --update-wishlist \
  --force-download
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
  --scryfall-cache .cache/scryfall-cardmarket \
  --pricing-mode scrape \
  --listing-language auto \
  --listing-condition nm \
  --listing-sample-size 5 \
  --scryfall-cardmarket-match \
  --scrape-fallback-to-priceguide \
  --strict-matching \
  --update-portfolio \
  --update-wishlist
```

## Parámetros clave

- `--pricing-mode scrape`: activa V7.1, Data Tables/Scryfall + scraping de listings.
- `--pricing-mode datatables`: usa solo Price Guides diarios.
- `--pricing-mode hybrid`: conserva el modo legacy de proveedor live externo con API key.
- `--scryfall-cardmarket-match` / `--no-scryfall-cardmarket-match`: activa o desactiva la resolución Scryfall -> `idProduct` para MTG singles.
- `--scrape-fallback-to-priceguide` / `--no-scrape-fallback-to-priceguide`: si Cardmarket bloquea el scraping, conserva o no el precio de Data Tables.
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
resolved                         Match y muestra suficiente.
insufficient_sample              idProduct resuelto, pero menos de 5 listings válidos.
unsupported_language             Idioma del item no mapeable.
scrape_blocked                   Cardmarket bloqueó el scraping y no hubo fallback.
scrape_blocked_fallback          Cardmarket bloqueó el scraping; se conserva Data Tables.
scrape_error                     Error general descargando o parseando la página.
scrape_error_fallback            Error scraping; se conserva Data Tables.
scrape_no_product_page           No se pudo localizar una página de producto scrapeable.
scrape_no_product_page_fallback  No se localizó página; se conserva Data Tables.
scrape_skipped_limit             Omitido por --max-scrape-items.
scrape_skipped_limit_fallback    Omitido por límite; se conserva Data Tables.
ambiguous                        Hay varios candidatos similares.
unmatched                        No hay match seguro.
manual                           Precio manual fijado en la web.
```

## Salidas generadas

```text
docs/data/market-prices.json
docs/data/market-prices.js
docs/data/cardmarket-matching-report.csv
docs/data/cardmarket-matching-report.json
```

El CSV de reporte incluye columnas específicas de V7.1:

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

En modo `scrape`, el override solo fija el producto. El precio final intentará salir de listings filtrados; si Cardmarket bloquea técnicamente el scraping y el fallback está activo, se usará Data Tables.

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
