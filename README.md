# Mi Coleccion TCGs - GitHub Pages

Estructura preparada para publicar desde la carpeta `docs` de GitHub Pages.

```text
docs/
  data/
    portfolio-data.js
    portfolio-data.json
  app.js
  index.html
  styles.css
README.md
```

Rutas usadas por el HTML:

```html
<link rel="stylesheet" href="./styles.css" />
<script src="./data/portfolio-data.js"></script>
<script src="./app.js"></script>
```

El archivo `portfolio-data.js` debe exponer `window.portfolioData`.
