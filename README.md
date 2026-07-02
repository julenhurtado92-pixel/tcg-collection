# Coleccion TCG Portfolio MVP

MVP para convertir tu Excel de coleccion en JSON y generar un dashboard HTML estatico inspirado en el tracker de Riftbound.

Este paquete ya se ha generado contra la hoja `Colección` de tu Excel. En este entorno no ha sido posible resolver DNS contra `api.scryfall.com`, por lo que las imagenes quedan preparadas para resolverse cuando ejecutes el script en local/GitHub con internet o desde el fallback del navegador.

## Resultado generado con tu Excel

- Hoja usada: `Colección`.
- Filas importadas: `3.857`.
- Compras activas: `3.287` filas.
- Ventas detectadas: `570` filas.
- Cantidad activa agregada: `7.139` unidades.
- Inversion activa desde Excel: `39.682,37 EUR`.
- Precio de mercado: pendiente para futura fase Cardmarket.
- Imagenes Scryfall: pendientes en el JSON generado offline, pero el HTML incluye boton/fallback para resolver imagenes visibles.

## Estructura

```text
/
  collection.xlsx                 # opcional; puedes usar tu nombre de Excel real
  requirements.txt
  scripts/
    excel_to_json.py
    enrich_scryfall.py
    build_portfolio_data.py
    build_all.py
  config/
    edition_aliases.json
    manual_scryfall_matches.json
  data/
    collection.raw.json
    collection.enriched.json
    scryfall-cache.json
  public/
    index.html
    app.js
    styles.css
    data/
      portfolio-data.js
      portfolio-data.json
```

## Flujo MVP

```text
Excel manual
  -> data/collection.raw.json
  -> data/collection.enriched.json
  -> public/data/portfolio-data.js
  -> public/index.html
```

## Uso local

No necesitas instalar dependencias externas.

```bash
python scripts/build_all.py --excel "collection.xlsx" --sheet "Colección"
```

Si tu Excel mantiene el nombre original:

```bash
python scripts/build_all.py --excel "MI COLECCIÓN TCGS.xlsx" --sheet "Colección"
```

Para probar solo la lectura de columnas:

```bash
python scripts/excel_to_json.py --excel "collection.xlsx" --sheet "Colección" --inspect
```

Despues abre:

```text
public/index.html
```

## Imagenes Scryfall

Hay dos modos:

1. **Script local/GitHub**: ejecuta el build sin `--offline`. El script `enrich_scryfall.py` consultara Scryfall y guardara resultados en `data/scryfall-cache.json`.
2. **Fallback navegador**: abre `public/index.html` y pulsa `Resolver imagenes visibles`. El navegador consultara Scryfall solo para las cartas visibles y guardara cache en `localStorage`.

Para generar la version offline, sin llamar a Scryfall:

```bash
python scripts/build_all.py --excel "collection.xlsx" --sheet "Colección" --offline
```

## Matching manual

Si una carta no resuelve bien, añade su `scryfallId` en:

```text
config/manual_scryfall_matches.json
```

Ejemplo:

```json
{
  "mtg-row-00014": {
    "scryfallId": "00000000-0000-0000-0000-000000000000"
  }
}
```

## Alias de ediciones

Puedes mapear nombres del Excel a codigos de set de Scryfall en:

```text
config/edition_aliases.json
```

Ejemplo:

```json
{
  "Modern Horizons 3": "mh3",
  "Modern Horizons 2": "mh2",
  "Dominaria United": "dmu"
}
```

## GitHub Actions como pulsador

El workflow `Build portfolio MVP` se puede lanzar desde la pestaña `Actions` con `Run workflow`.

Parametros:

- `excel_path`: ruta del Excel dentro del repositorio. Por defecto: `collection.xlsx`.
- `sheet_name`: por defecto: `Colección`.

El workflow regenera `data/` y `public/data/`, y hace commit si hay cambios.

## GitHub Pages

La carpeta publicable es:

```text
public/
```

Si el repositorio es publico, evita publicar `data/collection.raw.json` y `data/collection.enriched.json` si contienen datos privados de pedidos, vendedores o importes internos. El dashboard solo necesita `public/`.

## Limitaciones actuales

- Cardmarket no esta integrado todavia.
- `currentPrice` queda en `null` hasta que añadamos modulo de precios.
- Las ventas se importan como `Sold` y las compras como `Holding`.
- Scryfall solo cubre Magic; productos de Riftbound, One Piece, accesorios o refunds quedaran como pendientes de revision salvo que se añada otra fuente de imagenes.

## Proxima fase sugerida

1. Ejecutar el build con internet para poblar Scryfall.
2. Revisar las filas `needsReview`.
3. Añadir alias de ediciones frecuentes.
4. Decidir si publicas solo `public/` o todo el repositorio.
5. Diseñar el modulo local de precios Cardmarket bajo demanda.
