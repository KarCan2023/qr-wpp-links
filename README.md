
# Generador de links y QR de WhatsApp (Streamlit)

App lista para desplegar en **Streamlit Community Cloud** que:
- Genera links de WhatsApp (wa.me y api.whatsapp.com)
- Crea códigos QR para abrir la conversación con un mensaje prerellenado
- Soporta **carga en lote** desde CSV y exporta **ZIP** con QRs + `links.csv`
- Valida y normaliza números a formato **E.164** (e.g., `573105226770`) usando `phonenumbers`

> Diseñado para la **Iglesia Alianza Cristiana – Sede Orito Putumayo** 💚

## 🚀 Despliegue rápido

1. **Crea un repositorio en GitHub** y sube estos archivos (al menos `app.py` y `requirements.txt`).
2. Entra a **Streamlit Community Cloud** → *Deploy an app* → conecta tu repo y selecciona:
   - **Branch:** `main` (o el que uses)
   - **Main file:** `app.py`
3. Haz click en **Deploy**. ¡Listo!

## 📦 Estructura

```
.
├── app.py
├── requirements.txt
├── README.md
└── .streamlit/
    └── config.toml
```

## 🧑‍💻 Uso

### Modo **Individual**
1. Escribe el **teléfono** (con indicativo o selecciona el país para validar).
2. Redacta el **mensaje**. Puedes usar llaves como `{NOMBRE}` para pruebas.
3. Copia el **link** o descarga el **QR**.

### Modo **Lote (CSV)**
1. Descarga la **plantilla** desde la app o arma tu CSV con columnas:
   - `TELEFONO` (obligatoria)
   - `NOMBRE`, `ETIQUETA`, etc. (opcionales)
2. Escribe un **mensaje plantilla** usando llaves con nombres de columnas del CSV (ej: `{NOMBRE}`, `{ETIQUETA}`).
3. Descarga `links.csv` o el **ZIP** con todos los QRs + `links.csv`.

> Ejemplo de mensaje útil para campañas de la iglesia:
```
Hola 👋 vi la invitación ROMPIENDO EL TECHO. Quiero ir el 27. Soy {NOMBRE}. ¿Me guardan puesto?

#LaAlianza #LaAlianzaOrito #Orito
```

## 🛠️ Notas técnicas

- **Validación de teléfonos:** si `phonenumbers` no estuviera disponible, la app hace un *fallback* a “solo dígitos” y asume que ya incluyes indicativo.
- **QR:** requiere `qrcode[pil]` y `pillow` (ya incluidos en `requirements.txt`).

## 🔐 (Opcional) Extender hacia Meta Cloud API
Si luego quieres recibir estados o integrar Flows/Webhooks, crea otro servicio con `Flask`/`FastAPI` y usa un `VERIFY_TOKEN` (por ejemplo `alianza_orito_2025`) para la verificación del webhook. Esta app **no** necesita ese token: solo genera links/QR.

---

Hecho con ❤️ para **#LaAlianza #LaAlianzaOrito #Orito**.
