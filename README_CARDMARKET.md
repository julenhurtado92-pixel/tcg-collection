# Actualización de precios Cardmarket V8

V8 mantiene el pipeline V7.1.1, pero añade una capa específica para **Riftbound** basada en la imagen ya validada dentro de `portfolio-data.json`.

El problema detectado era que Cardmarket Data Tables suele devolver `idExpansion`, pero muchas veces deja `expansionName` vacío. En MTG lo resolvimos con Scryfall. En Riftbound no conviene hacer matching sólo por nombre, porque una carta puede tener varias versiones con el mismo nombre. Por eso V8 usa el código de carta extraído de la imagen actual como fuente de verdad.

## Flujo actual

1. **Data Tables** cargan catálogo y Price Guides diarios de Cardmarket.
2. Para **MTG singles**, Scryfall se usa como apoyo para obtener el `cardmarket_id` exacto cuando está disponible.
3. Para **Riftbound singles**, V8 extrae el código desde la imagen ya revisada en el JSON, por ejemplo:
   - `https://images.scrydex.com/riftbound/SFD-225/medium` → `SFD-225`
   - `https://static.dotgg.gg/riftbound/cards/OGN-246b.webp` → `OGN-246B`
4. Con ese código se deduce el set/expansión Cardmarket esperada:
   - `OGN` → Origins
   - `SFD` → Spiritforged
   - `UNL` → Unleashed
   - promos cuando la edición o el código lo indiquen.
5. Si Cardmarket no expone claramente `V.1`, `V.2`, `V.3` o `V.4` en Data Tables, V8 puede usar una heurística de proximidad precio/coste para desempatar versiones con el mismo nombre.
6. El script intenta scraping de listings Cardmarket con idioma + condición mínima.
7. Si Cardmarket bloquea técnicamente el scraping, se conserva el precio Data Tables como fallback transparente.
8. Si el scraping funciona pero hay menos de 5 ofertas válidas, el item queda como `insufficient_sample` y no se valora con fallback.

## One Piece desactivado temporalmente

El material de One Piece se ha eliminado de los JSON generados incluidos en esta versión. El soporte de filtros, estados y juego sigue presente en el código para poder reactivarlo más adelante.

Además, `scripts/generate_portfolio_data.py` tiene ahora:

```bash
--exclude-tcgs onepiece
```

como valor por defecto. Si en el futuro quieres reincorporarlo, bastaría con regenerar usando:

```bash
python scripts/generate_portfolio_data.py --exclude-tcgs ""
```

## GitHub Actions

El workflow `Actualizar precios Cardmarket` queda configurado por defecto con:

```text
pricing_mode = scrape
listing_language = auto
listing_condition = nm
listing_sample_size = 5
scryfall_cardmarket_match = true
riftbound_image_match = true
riftbound_price_heuristic = true
scrape_fallback_to_priceguide = true
```

No necesitas `CARDMARKET_LIVE_API_KEY`.

Opcionalmente puedes crear este secreto si tu sesión local de Cardmarket ayuda a evitar páginas incompletas o bloqueos:

```text
CARDMARKET_COOKIE
```

El workflow lo pasa como variable de entorno, pero no lo escribe en JSON, CSV ni logs. Aunque haya cookie, Cardmarket puede bloquear peticiones desde GitHub Actions; por eso V8 conserva el fallback a Data Tables.

## Uso local V8

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
  --riftbound-image-match \
  --riftbound-price-heuristic \
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
  --riftbound-image-match \
  --riftbound-price-heuristic \
  --scrape-fallback-to-priceguide \
  --strict-matching \
  --update-portfolio \
  --update-wishlist
```

## Parámetros clave

- `--pricing-mode scrape`: Data Tables/Scryfall/Riftbound image match + scraping de listings Cardmarket.
- `--pricing-mode datatables`: usa sólo Price Guides diarios.
- `--pricing-mode hybrid`: conserva el modo legacy de proveedor live externo con API key.
- `--scryfall-cardmarket-match` / `--no-scryfall-cardmarket-match`: activa o desactiva Scryfall → `idProduct` para MTG singles.
- `--scryfall-sleep 0.25`: pausa entre llamadas a Scryfall.
- `--scryfall-max-retries 4`: reintentos ante HTTP 429/5xx de Scryfall.
- `--riftbound-image-match` / `--no-riftbound-image-match`: activa o desactiva el resolver de Riftbound por código de imagen.
- `--riftbound-price-heuristic` / `--no-riftbound-price-heuristic`: permite usar proximidad de precio/coste para desempatar versiones Riftbound cuando Cardmarket no expone claramente la versión.
- `--riftbound-image-min-score 75`: puntuación mínima para aceptar el match por imagen.
- `--scrape-fallback-to-priceguide` / `--no-scrape-fallback-to-priceguide`: si Cardmarket bloquea el scraping, conserva o no el precio de Data Tables.
- `--listing-language auto`: usa el idioma de cada item.
- `--listing-condition nm`: condición mínima NM; acepta NM y MT.
- `--listing-sample-size 5`: media de las 5 ofertas válidas más baratas.
- `--exclude-uk` / `--no-exclude-uk`: excluye o permite vendedores de Reino Unido.
- `--require-europe` / `--no-require-europe`: exige país europeo conocido o permite cualquier país.
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

El CSV de reporte incluye columnas específicas de V8:

```text
riftboundImageStatus
riftboundImageCode
riftboundExpectedExpansions
riftboundVersionTarget
riftboundImageHeuristic
scryfallResolverStatus
scryfallCardmarketId
scrapeStatus
scrapeReason
fallbackPriceGuideUnit
```

## Overrides manuales

Los overrides por item siguen igual:

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

También puedes fijar versiones Riftbound por código de imagen dentro de `docs/data/cardmarket-overrides.json`:

```json
{
  "items": {},
  "wishlistItems": {},
  "riftboundImageCodes": {
    "SFD-225": {
      "idProduct": 866786,
      "notes": "Versión confirmada manualmente por imagen"
    }
  }
}
```

El override de Riftbound por código tiene prioridad sobre la heurística.

## Modo seguro sin scraping

Para seguir usando sólo Data Tables:

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
