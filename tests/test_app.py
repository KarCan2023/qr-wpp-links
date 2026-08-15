"""Tests de la app.

El QR estuvo roto desde el primer commit y nadie lo notó porque nada ejecutaba la
app: `st.image()` recibía un `qrcode.image.pil.PilImage` (un envoltorio, no un
`PIL.Image.Image`) y reventaba con "a bytes-like object is required, not 'PilImage'".
`test_la_app_arranca_sin_excepciones` y `test_qr_es_un_png_valido` cubren
exactamente esa regresión.

Correr con:  pytest -q
"""

import io
import sys
import urllib.parse
from pathlib import Path
from zipfile import ZipFile

import pytest
from PIL import Image
from streamlit.testing.v1 import AppTest

RAIZ = Path(__file__).resolve().parent.parent
APP = str(RAIZ / "app.py")
sys.path.insert(0, str(RAIZ))

import app  # noqa: E402


# --- QR -------------------------------------------------------------------

def test_qr_es_un_png_valido():
    png = app.make_qr("https://wa.me/573105226770?text=hola")

    assert isinstance(png, bytes), "make_qr debe devolver bytes, no un objeto de qrcode"
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    with Image.open(io.BytesIO(png)) as im:
        assert im.format == "PNG"
        assert im.size[0] > 0


def test_qr_de_impresion_es_mas_grande_que_el_de_pantalla():
    link = "https://wa.me/573105226770?text=hola"
    pantalla = Image.open(io.BytesIO(app.make_qr(link, box_size=app.BOX_SIZE_PANTALLA)))
    impresion = Image.open(io.BytesIO(app.make_qr(link, box_size=app.BOX_SIZE_IMPRESION)))

    assert impresion.size[0] > pantalla.size[0] * 3
    assert impresion.size[0] >= 1000, "muy pequeño para imprimir en un volante"


def test_el_qr_codifica_el_link_completo():
    """Un mensaje largo no debe truncarse: qrcode sube de versión con fit=True."""
    texto = "Hola " * 200
    link = app.build_link("573105226770", texto)
    png = app.make_qr(link)

    with Image.open(io.BytesIO(png)) as im:
        assert im.size[0] > 400, "el QR no creció para acomodar el mensaje largo"


# --- Links y teléfonos ----------------------------------------------------

@pytest.mark.parametrize(
    "crudo,esperado",
    [
        ("+57 310 123 4567", "573101234567"),
        ("3027248068", "573027248068"),
        ("(+57) 311-555-7788", "573115557788"),
        ("", ""),
        ("123", ""),
        ("no soy un teléfono", ""),
    ],
)
def test_normalize_phone(crudo, esperado):
    assert app.normalize_phone(crudo, "CO") == esperado


def test_build_link_codifica_el_texto():
    link = app.build_link("573105226770", "Hola ¿qué tal?\n#Orito")

    assert link.startswith("https://wa.me/573105226770?text=")
    texto = urllib.parse.unquote(link.split("text=", 1)[1])
    assert texto == "Hola ¿qué tal?\n#Orito"


def test_build_link_api():
    link = app.build_link("573105226770", "hola", provider="api")
    assert link.startswith("https://api.whatsapp.com/send?phone=573105226770&text=")


# --- Plantillas -----------------------------------------------------------

def test_render_template_sustituye_variables():
    assert app.render_template("Hola {NOMBRE}", {"NOMBRE": "María"}) == "Hola María"


@pytest.mark.parametrize("malo", ["hola {NO_EXISTE}", "50% {descuento", "{}"])
def test_render_template_no_tumba_la_app(malo):
    with pytest.raises(ValueError):
        app.render_template(malo, {"NOMBRE": "Carlos"})


def test_las_plantillas_por_defecto_van_en_direcciones_opuestas():
    """El default del lote lo envía la iglesia; el individual, el visitante."""
    assert "Soy {NOMBRE}" in app.DEFAULT_MESSAGE_ENTRANTE
    assert "Soy {NOMBRE}" not in app.DEFAULT_MESSAGE_SALIENTE
    assert "{NOMBRE}" in app.DEFAULT_MESSAGE_SALIENTE


# --- Nombres de archivo ---------------------------------------------------

def test_nombre_archivo_qr_incluye_fila_y_telefono():
    fila = {"FILA": 1, "NOMBRE": "María José", "TELEFONO_E164": "573101234567"}
    assert app.nombre_archivo_qr(fila) == "qr_001_Mar-a-Jos_573101234567.png"


def test_nombre_archivo_qr_sin_nombre():
    assert app.nombre_archivo_qr({"FILA": 7, "TELEFONO_E164": "573101234567"}) == (
        "qr_007_573101234567.png"
    )


def test_telefonos_repetidos_no_se_pisan_en_el_zip():
    filas = [
        {"FILA": 1, "NOMBRE": "Ana", "TELEFONO_E164": "573101234567"},
        {"FILA": 2, "NOMBRE": "Ana", "TELEFONO_E164": "573101234567"},
    ]
    assert len({app.nombre_archivo_qr(f) for f in filas}) == 2


# --- La app completa ------------------------------------------------------

def test_la_app_arranca_sin_excepciones():
    at = AppTest.from_file(APP, default_timeout=60).run()

    assert not at.exception, [str(e.value) for e in at.exception]


def test_muestra_el_qr_y_sus_botones_de_descarga():
    at = AppTest.from_file(APP, default_timeout=60).run()

    etiquetas = [b.label for b in at.get("download_button")]
    assert any("pantalla" in e for e in etiquetas), etiquetas
    assert any("imprimir" in e for e in etiquetas), etiquetas


def test_un_telefono_invalido_avisa_en_vez_de_reventar():
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.text_input[0].set_value("123").run()

    assert not at.exception
    assert at.warning, "debería avisar que el teléfono no es válido"


def test_el_zip_trae_un_qr_por_contacto_y_el_csv():
    """Reproduce el flujo del modo Lote sin pasar por el file_uploader."""
    import pandas as pd

    df = pd.read_csv(RAIZ / "sample_contacts.csv", dtype=str).fillna("")
    filas = []
    for idx, row in df.iterrows():
        contexto = {k: str(v) for k, v in row.items()}
        telefono = app.normalize_phone(row["TELEFONO"], "CO")
        assert telefono, f"el CSV de ejemplo trae un teléfono inválido: {row['TELEFONO']}"
        texto = app.render_template(app.DEFAULT_MESSAGE_SALIENTE, contexto)
        filas.append(
            {"FILA": idx + 1, **contexto, "TELEFONO_E164": telefono,
             "LINK": app.build_link(telefono, texto)}
        )

    res = pd.DataFrame(filas)
    # El CSV de salida conserva las columnas del de entrada.
    assert {"NOMBRE", "ETIQUETA"} <= set(res.columns)

    csv_bytes = res.to_csv(index=False).encode("utf-8")
    nombres = tuple(app.nombre_archivo_qr(r) for _, r in res.iterrows())
    zip_bytes = app.qr_zip.__wrapped__(
        tuple(res["LINK"]), nombres, csv_bytes, app.BOX_SIZE_PANTALLA
    )

    with ZipFile(io.BytesIO(zip_bytes)) as zf:
        contenido = zf.namelist()
        assert "links.csv" in contenido
        assert len(contenido) == len(res) + 1
        assert zf.read(contenido[0])[:8] == b"\x89PNG\r\n\x1a\n"
