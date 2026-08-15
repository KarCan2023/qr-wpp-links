
import io
import re
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import List, Dict

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Generador de links y QR de WhatsApp", page_icon="💬", layout="centered")

# Optional dependency for robust phone validation/formatting
try:
    import phonenumbers
    from phonenumbers.phonenumberutil import NumberParseException
except Exception:
    phonenumbers = None

# Optional dependency for QR
try:
    import qrcode
    from qrcode.image.pil import PilImage
    from PIL import Image, ImageFilter, ImageOps
except Exception:
    qrcode = None
    PilImage = None
    Image = None
    ImageFilter = None
    ImageOps = None

# Optional: rasterizar logos SVG. Necesita libcairo2 (ver packages.txt).
# Si falta, la app sigue funcionando con logos PNG/JPG.
try:
    import cairosvg
except Exception:
    cairosvg = None

APP_TITLE = "Generador de links y QR de WhatsApp"
APP_SUBTITLE = "Iglesia Alianza Cristiana – Sede Orito Putumayo"

HASHTAGS = "#LaAlianza #LaAlianzaOrito #Orito"

# Los dos modos generan mensajes en direcciones OPUESTAS y necesitan plantillas distintas.
#
# Individual: el QR va en el volante/pendón. Quien escanea es el visitante, y el link
# apunta al teléfono de la iglesia -> el mensaje se redacta en primera persona del visitante.
DEFAULT_MESSAGE_ENTRANTE = (
    "Hola 👋 vi la invitación ROMPIENDO EL TECHO. Quiero ir el 27. "
    "Soy {NOMBRE}. ¿Me guardan puesto?\n\n" + HASHTAGS
)

# Lote: cada link apunta al teléfono DEL CONTACTO, así que quien envía es la iglesia
# -> el mensaje se redacta en primera persona de la iglesia, dirigido a {NOMBRE}.
DEFAULT_MESSAGE_SALIENTE = (
    "Hola {NOMBRE} 👋 Te esperamos en ROMPIENDO EL TECHO el 27. "
    "¿Te guardamos puesto?\n\n" + HASHTAGS
)

# Tamaño de módulo (px por cuadro) para QR de pantalla y para QR de impresión.
BOX_SIZE_PANTALLA = 10
BOX_SIZE_IMPRESION = 40

# Logo al centro del QR.
# Si existe assets/logo.svg (o .png) se usa por defecto; también se puede subir uno.
ASSETS = Path(__file__).parent / "assets"
LOGO_POR_DEFECTO = next(
    (p for p in (ASSETS / "logo.svg", ASSETS / "logo.png") if p.exists()), None
)
# Probado con el detector de OpenCV: hasta 30% se lee, 40% ya no. 22% deja margen.
LOGO_PCT_MAX = 0.30
LOGO_PCT_DEFECTO = 0.22

def normalize_phone(raw: str, default_region: str = "CO") -> str:
    """Return E.164 like 573105226770. Falls back to digits-only if phonenumbers not available."""
    s = str(raw).strip()
    if not s:
        return ""
    if phonenumbers:
        try:
            num = phonenumbers.parse(s, default_region)
            if not phonenumbers.is_possible_number(num) or not phonenumbers.is_valid_number(num):
                return ""
            return phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164).replace("+", "")
        except NumberParseException:
            return ""
    # Fallback: keep digits and assume already includes country code
    digits = re.sub(r"\D", "", s)
    return digits

def build_link(phone_e164: str, text: str, provider: str = "wa.me") -> str:
    encoded = urllib.parse.quote(text, safe="")
    if provider == "api":
        return f"https://api.whatsapp.com/send?phone={phone_e164}&text={encoded}"
    else:
        return f"https://wa.me/{phone_e164}?text={encoded}"

def cargar_logo(datos: bytes, nombre_archivo: str, lado: int):
    """Devuelve el logo como PIL RGBA, ajustado a una caja de `lado` px sin deformarlo.

    Acepta SVG (se rasteriza al tamaño final, por eso conviene sobre un PNG: cada QR
    lo genera nítido, tanto el de 370 px de pantalla como el de 2760 px de impresión)
    y también PNG/JPG.
    """
    if nombre_archivo.lower().endswith(".svg"):
        if not cairosvg:
            raise RuntimeError(
                "Para usar un logo SVG hace falta `cairosvg` (y libcairo2 en el sistema). "
                "Súbelo como PNG con fondo transparente, o revisa packages.txt."
            )
        # Solo output_width: cairosvg conserva la proporción del viewBox.
        datos = cairosvg.svg2png(bytestring=datos, output_width=lado)

    logo = Image.open(io.BytesIO(datos)).convert("RGBA")
    return ImageOps.contain(logo, (lado, lado), Image.LANCZOS)


def pegar_logo(qr_img, logo, halo: int):
    """Pega el logo al centro sobre un halo blanco que sigue su silueta.

    Un recuadro blanco cuadrado se ve mal con logos de contorno irregular, así que
    dilatamos el canal alfa: el blanco abraza la forma real del logo.
    """
    if halo > 0:
        radio = halo * 2 + 1
        mascara = logo.getchannel("A").filter(ImageFilter.MaxFilter(radio))
        fondo = Image.new("RGBA", logo.size, (255, 255, 255, 0))
        fondo.putalpha(mascara)
        capa = Image.alpha_composite(fondo, logo)
    else:
        capa = logo

    x = (qr_img.size[0] - capa.size[0]) // 2
    y = (qr_img.size[1] - capa.size[1]) // 2
    qr_img.paste(capa, (x, y), capa)
    return qr_img


def make_qr(
    link: str,
    box_size: int = 10,
    border: int = 4,
    logo: bytes = b"",
    logo_nombre: str = "",
    logo_pct: float = LOGO_PCT_DEFECTO,
) -> bytes:
    """Genera el QR y lo devuelve como bytes PNG.

    Devolvemos bytes (y no el objeto de qrcode) porque `qr.make_image()` retorna un
    `qrcode.image.pil.PilImage`, que es un envoltorio y NO una instancia de
    `PIL.Image.Image`; `st.image()` lo rechaza con
    "TypeError: a bytes-like object is required, not 'PilImage'".
    Los bytes PNG los aceptan tanto `st.image` como `st.download_button` y el ZIP.
    """
    if not qrcode:
        raise RuntimeError(
            "Falta la dependencia `qrcode[pil]`. Instálala con: pip install \"qrcode[pil]\""
        )

    # Con logo hay que subir la corrección de errores a H (recupera 30% en vez de 15%),
    # porque el logo tapa módulos. El QR se vuelve más denso: con un link de ~230
    # caracteres pasa de 61x61 a 81x81 módulos.
    qr = qrcode.QRCode(
        version=None,
        error_correction=(
            qrcode.constants.ERROR_CORRECT_H if logo else qrcode.constants.ERROR_CORRECT_M
        ),
        box_size=box_size,
        border=border,
    )
    qr.add_data(link)
    qr.make(fit=True)

    # image_factory explícito: si Pillow no estuviera disponible, qrcode caería en
    # PyPNGImage y `save(..., format="PNG")` fallaría con un kwarg inesperado.
    img = qr.make_image(image_factory=PilImage, fill_color="black", back_color="white")

    if logo:
        img = img.get_image().convert("RGBA")
        lado = int(img.size[0] * min(logo_pct, LOGO_PCT_MAX))
        img = pegar_logo(
            img,
            cargar_logo(logo, logo_nombre, lado),
            halo=max(1, int(lado * 0.06)),
        ).convert("RGB")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

@st.cache_data(show_spinner=False, max_entries=512)
def qr_png(link: str, box_size: int = BOX_SIZE_PANTALLA, border: int = 4, **logo_kw) -> bytes:
    """`make_qr` memoizado. Streamlit reejecuta el script entero en cada interacción;
    sin caché, mover un slider regenera todos los QR del lote desde cero."""
    return make_qr(link, box_size=box_size, border=border, **logo_kw)

@st.cache_data(show_spinner="Generando QRs…", max_entries=8)
def qr_zip(links: tuple, nombres: tuple, csv_bytes: bytes, box_size: int, **logo_kw) -> bytes:
    """Arma el ZIP completo una sola vez por combinación de links/resolución."""
    from zipfile import ZIP_DEFLATED, ZipFile

    zip_buf = io.BytesIO()
    with ZipFile(zip_buf, "w", ZIP_DEFLATED) as zf:
        for nombre, link in zip(nombres, links):
            zf.writestr(nombre, make_qr(link, box_size=box_size, **logo_kw))
        zf.writestr("links.csv", csv_bytes)
    return zip_buf.getvalue()

def selector_de_logo(key: str) -> Dict:
    """Widget compartido por ambas pestañas. Devuelve los kwargs de logo para make_qr."""
    if not qrcode:
        return {}

    tiene_defecto = LOGO_POR_DEFECTO is not None
    etiqueta = (
        f"🎨 Poner el logo al centro ({LOGO_POR_DEFECTO.name})"
        if tiene_defecto
        else "🎨 Poner un logo al centro"
    )
    if not st.checkbox(etiqueta, value=tiene_defecto, key=f"logo_on_{key}"):
        return {}

    subido = st.file_uploader(
        "Logo (SVG, PNG o JPG). El SVG es el mejor: se rasteriza nítido a cualquier tamaño.",
        type=["svg", "png", "jpg", "jpeg"],
        key=f"logo_file_{key}",
    )
    if subido is not None:
        datos, nombre = subido.getvalue(), subido.name
    elif tiene_defecto:
        datos, nombre = LOGO_POR_DEFECTO.read_bytes(), LOGO_POR_DEFECTO.name
    else:
        st.info("Sube un logo para verlo dentro del QR.")
        return {}

    if nombre.lower().endswith(".svg") and not cairosvg:
        st.error(
            "Este servidor no puede rasterizar SVG (falta libcairo2). "
            "Sube el logo como PNG con fondo transparente."
        )
        return {}

    pct = st.slider(
        "Tamaño del logo (% del ancho del QR)",
        10, int(LOGO_PCT_MAX * 100), int(LOGO_PCT_DEFECTO * 100),
        key=f"logo_pct_{key}",
        help="Por encima del 30% los lectores empiezan a fallar.",
    ) / 100

    st.caption(
        "Con logo, la corrección de errores sube a nivel H y el QR se vuelve más denso. "
        "**Pruébalo con tu celular antes de mandarlo a imprimir.**"
    )
    return {"logo": datos, "logo_nombre": nombre, "logo_pct": pct}

def nombre_archivo_qr(row) -> str:
    """qr_001_Maria_573101234567.png — el número de fila evita que dos contactos
    con el mismo teléfono se sobrescriban dentro del ZIP."""
    nombre = re.sub(r"[^A-Za-z0-9]+", "-", str(row.get("NOMBRE", "") or "")).strip("-")
    partes = [f"qr_{int(row['FILA']):03d}", nombre, str(row["TELEFONO_E164"])]
    return "_".join(p for p in partes if p) + ".png"

def qr_dimensiones(png: bytes) -> str:
    """Devuelve '1480 × 1480 px (≈12.5 cm a 300 dpi)' para orientar al imprimir."""
    if not Image:
        return ""
    with Image.open(io.BytesIO(png)) as im:
        w, h = im.size
    return f"{w} × {h} px (≈{w / 300 * 2.54:.1f} cm a 300 dpi)"

def render_template(text: str, context: Dict[str, str]) -> str:
    """Aplica .format() sin tumbar la app si el mensaje trae llaves sueltas.

    Un mensaje como "50% {descuento" o "{OTRA_COSA}" lanza ValueError/KeyError/IndexError
    dentro de str.format; aquí lo convertimos en un error legible para quien usa la app.
    """
    try:
        return text.format(**context)
    except KeyError as ke:
        raise ValueError(f"La variable {ke} no existe. Variables disponibles: {', '.join(context) or '(ninguna)'}.")
    except (IndexError, ValueError):
        raise ValueError(
            "El mensaje tiene llaves { } mal formadas. Usa {NOMBRE} para personalizar, "
            "o escribe {{ y }} si necesitas una llave literal."
        )


def render_header():
    st.title(f"💬 {APP_TITLE}")
    st.caption(APP_SUBTITLE)
    with st.expander("📖 Versículo de ánimo (Colosenses 3:23)", expanded=False):
        st.write("“Y todo lo que hagáis, hacedlo de corazón, como para el Señor y no para los hombres.” (RVR1960)")

def single_link_ui():
    st.subheader("🎯 Generar un link/QR")
    cols = st.columns([1, 1])
    with cols[0]:
        phone = st.text_input("Teléfono destinatario (incluye indicativo o escoge país abajo)", "3105226770")
        region = st.selectbox("País por defecto para validar", options=["CO", "US", "MX", "PE", "EC", "AR", "CL", "VE", "BR", "ES"], index=0)
    with cols[1]:
        provider = st.radio("Proveedor de link", options=["wa.me", "api"], index=0, help="Ambos son válidos; 'api' usa api.whatsapp.com.")
        add_newlines = st.checkbox("Insertar saltos de línea entre párrafos", value=True)

    st.info(
        "📤 Este QR lo escanea **el visitante** y le escribe **a la iglesia**, "
        "así que el mensaje va redactado en primera persona de quien asiste.",
        icon="ℹ️",
    )

    message = st.text_area(
        "Mensaje que enviará quien escanee el QR",
        DEFAULT_MESSAGE_ENTRANTE,
        height=160,
        help="Usa {NOMBRE} para ver la vista previa personalizada.",
    )
    nombre_demo = st.text_input("Vista previa con nombre:", "Carlos")
    try:
        preview_text = render_template(message, {"NOMBRE": nombre_demo})
    except ValueError as e:
        st.error(f"⚠️ {e}")
        return
    if add_newlines:
        preview_text = preview_text.replace("\\n", "\n")

    phone_e164 = normalize_phone(phone, region)
    if not phone_e164:
        st.warning("👉 Ingresa un teléfono válido (con indicativo o selecciona el país correcto).")
        return

    link = build_link(phone_e164, preview_text, provider="api" if provider == "api" else "wa.me")
    st.code(link, language="markdown")

    # Botones de copia/acción
    st.link_button("🔗 Abrir link en nueva pestaña", link)

    # QR
    st.markdown("---")
    st.subheader("🧩 Código QR")
    box = st.slider("Tamaño del cuadro", 5, 20, BOX_SIZE_PANTALLA)
    border = st.slider("Borde", 2, 10, 4)
    logo_kw = selector_de_logo("individual")
    try:
        png = qr_png(link, box_size=box, border=border, **logo_kw)
        png_impresion = qr_png(link, box_size=BOX_SIZE_IMPRESION, border=border, **logo_kw)
    except Exception as e:
        st.error(f"No se pudo generar el QR: {e}")
        return

    st.image(png, caption="Escanéame para abrir WhatsApp")

    cols = st.columns(2)
    with cols[0]:
        st.download_button(
            "⬇️ QR para pantalla (PNG)",
            data=png,
            file_name=f"qr_whatsapp_{phone_e164}.png",
            mime="image/png",
            help=qr_dimensiones(png),
            width="stretch",
        )
    with cols[1]:
        st.download_button(
            "🖨️ QR para imprimir (PNG)",
            data=png_impresion,
            file_name=f"qr_whatsapp_{phone_e164}_impresion.png",
            mime="image/png",
            help=qr_dimensiones(png_impresion),
            type="primary",
            width="stretch",
        )
    st.caption(
        f"Pantalla: {qr_dimensiones(png)} · Impresión: {qr_dimensiones(png_impresion)}. "
        "Para volantes y pendones usa siempre el de impresión."
    )

def bulk_ui():
    st.subheader("📦 Generar links/QR en lote (CSV)")
    with st.expander("📄 Plantilla CSV (descárgala y edítala)"):
        sample = pd.DataFrame({
            "NOMBRE": ["María", "Juan", "Luisa"],
            "TELEFONO": ["+57 310 123 4567", "3027248068", "(+57) 311-555-7788"],
            "ETIQUETA": ["Rompiendo el Techo", "Reunión Jueves", "Encuentro Jóvenes"]
        })
        st.dataframe(sample, width="stretch")
        st.download_button(
            "⬇️ Descargar plantilla sample_contacts.csv",
            data=sample.to_csv(index=False).encode("utf-8"),
            file_name="sample_contacts.csv",
            mime="text/csv"
        )

    uploaded = st.file_uploader("Sube tu CSV con columnas: TELEFONO, opcionalmente NOMBRE y otras variables", type=["csv"])
    region = st.selectbox("País por defecto para validar", options=["CO", "US", "MX", "PE", "EC", "AR", "CL", "VE", "BR", "ES"], index=0, key="bulk_region")
    provider = st.radio("Proveedor de link", options=["wa.me", "api"], index=0, horizontal=True, key="bulk_provider")

    st.info(
        "📥 Aquí cada link abre el chat **con ese contacto**, así que el mensaje lo envía "
        "**la iglesia** y va dirigido a {NOMBRE}. No uses el texto del modo Individual: "
        "terminarías escribiéndole a María un mensaje que dice «Soy María».",
        icon="ℹ️",
    )

    template = st.text_area(
        "Mensaje plantilla que enviará la iglesia",
        DEFAULT_MESSAGE_SALIENTE,
        height=160,
        help="Usa llaves con los nombres de las columnas del CSV: {NOMBRE}, {ETIQUETA}, etc.",
    )

    if uploaded is not None:
        try:
            df = pd.read_csv(uploaded, dtype=str).fillna("")
        except Exception as e:
            st.error(f"No se pudo leer el CSV: {e}")
            return

        if "TELEFONO" not in df.columns:
            st.error("La columna TELEFONO es obligatoria.")
            return

        # Construimos resultados
        rows = []
        bad_rows = []
        for idx, row in df.iterrows():
            raw_phone = row.get("TELEFONO", "")
            phone_e164 = normalize_phone(raw_phone, region)
            context = {k: str(v) for k, v in row.items()}
            try:
                text = render_template(template, context)
            except ValueError as e:
                st.error(f"Fila {idx + 1}: {e}")
                return

            if not phone_e164:
                bad_rows.append(idx + 1)
                continue

            link = build_link(phone_e164, text, provider="api" if provider == "api" else "wa.me")
            # Arrastramos las columnas originales (NOMBRE, ETIQUETA, …) para que el CSV de
            # salida sea usable en Excel sin tener que cruzarlo a mano con el de entrada.
            # Si el CSV ya trae una columna llamada FILA/TELEFONO_E164/LINK, gana la generada.
            rows.append({"FILA": idx + 1, **context, "TELEFONO_E164": phone_e164, "LINK": link})

        result_df = pd.DataFrame(rows)
        st.write(f"✅ Links generados: {len(result_df)}")
        if bad_rows:
            st.warning(f"⚠️ {len(bad_rows)} filas con teléfono inválido: {bad_rows}")

        st.dataframe(result_df, width="stretch")

        csv_bytes = result_df.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Descargar links.csv", data=csv_bytes, file_name="links.csv", mime="text/csv")

        # Paquete de QRs en ZIP
        if qrcode and not result_df.empty:
            para_imprimir = st.checkbox(
                "🖨️ QRs en alta resolución (para imprimir)",
                value=False,
                help="Sube cada QR a un tamaño apto para volantes; el ZIP pesa más.",
            )
            box_size = BOX_SIZE_IMPRESION if para_imprimir else BOX_SIZE_PANTALLA
            logo_kw = selector_de_logo("lote")

            try:
                nombres = tuple(nombre_archivo_qr(r) for _, r in result_df.iterrows())
                zip_bytes = qr_zip(
                    tuple(result_df["LINK"]), nombres, csv_bytes, box_size, **logo_kw
                )
            except Exception as e:
                st.error(f"No se pudo armar el paquete de QRs: {e}")
                return

            st.download_button(
                "⬇️ Descargar paquete de QRs + links (.zip)",
                data=zip_bytes,
                file_name=f"qr_links_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
                mime="application/zip"
            )
            st.caption(f"{len(result_df)} QR · {len(zip_bytes) / 1024:.0f} KB")
        elif not qrcode:
            st.info("Instala `qrcode[pil]` para exportar QRs en lote.")

def footer():
    st.markdown("---")
    st.caption("Hecho con ❤️ para #LaAlianza #LaAlianzaOrito #Orito")

def main():
    render_header()
    tab1, tab2 = st.tabs(["Individual", "Lote"])
    with tab1:
        single_link_ui()
    with tab2:
        bulk_ui()
    footer()

if __name__ == "__main__":
    main()
