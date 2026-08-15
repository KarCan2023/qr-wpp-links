
import io
import re
import urllib.parse
from datetime import datetime
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
    from PIL import Image
except Exception:
    qrcode = None
    PilImage = None
    Image = None

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

def make_qr(link: str, box_size: int = 10, border: int = 4) -> bytes:
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

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(link)
    qr.make(fit=True)

    # image_factory explícito: si Pillow no estuviera disponible, qrcode caería en
    # PyPNGImage y `save(..., format="PNG")` fallaría con un kwarg inesperado.
    img = qr.make_image(image_factory=PilImage, fill_color="black", back_color="white")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

@st.cache_data(show_spinner=False, max_entries=512)
def qr_png(link: str, box_size: int = BOX_SIZE_PANTALLA, border: int = 4) -> bytes:
    """`make_qr` memoizado. Streamlit reejecuta el script entero en cada interacción;
    sin caché, mover un slider regenera todos los QR del lote desde cero."""
    return make_qr(link, box_size=box_size, border=border)

@st.cache_data(show_spinner="Generando QRs…", max_entries=8)
def qr_zip(links: tuple, nombres: tuple, csv_bytes: bytes, box_size: int) -> bytes:
    """Arma el ZIP completo una sola vez por combinación de links/resolución."""
    from zipfile import ZIP_DEFLATED, ZipFile

    zip_buf = io.BytesIO()
    with ZipFile(zip_buf, "w", ZIP_DEFLATED) as zf:
        for nombre, link in zip(nombres, links):
            zf.writestr(nombre, make_qr(link, box_size=box_size))
        zf.writestr("links.csv", csv_bytes)
    return zip_buf.getvalue()

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
    try:
        png = qr_png(link, box_size=box, border=border)
        png_impresion = qr_png(link, box_size=BOX_SIZE_IMPRESION, border=border)
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

            try:
                nombres = tuple(nombre_archivo_qr(r) for _, r in result_df.iterrows())
                zip_bytes = qr_zip(
                    tuple(result_df["LINK"]), nombres, csv_bytes, box_size
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
