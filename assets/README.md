# assets

Deja aquí el logo de la iglesia como **`logo.svg`** (preferido) o **`logo.png`**.
Si el archivo existe, la app lo ofrece marcado por defecto para ponerlo al centro del QR;
si no, se puede subir uno desde la propia app sin tocar el repo.

Requisitos del archivo:

- **SVG**: con el texto convertido a curvas/paths (las fuentes del diseñador no están en el
  servidor y el texto se rompería al rasterizar) y con `viewBox` definido.
- **PNG**: 1000 px o más, con fondo transparente.
- De preferencia cuadrado o casi; si no, se ajusta sin deformarse.

Rasterizar SVG necesita `cairosvg` + `libcairo2` (ver `requirements.txt` y `packages.txt`).
Sin eso la app sigue funcionando, pero solo acepta logos PNG/JPG.
