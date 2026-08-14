import pytest
from intentlang import lexicon
from intentlang.relex import round_trip
from intentlang.resolve import resolve


@pytest.fixture(scope="module", autouse=True)
def _instalar():
    for lang in ("es", "en", "zh"):
        lexicon.ensure_installed(lang)


def test_usa_una_palabra_DISTINTA_a_la_del_usuario():
    """El test que convierte el round-trip en deteccion de fraude.

    Si devuelve exactamente la palabra escrita, la capa semantica no corrio
    y estamos viendo un passthrough de strings.
    """
    intent = resolve("copia el archivo", "es")
    frase = round_trip(intent, "es")
    assert "copiar" not in frase, f"passthrough de strings: {frase!r}"


def test_puede_devolver_en_otro_idioma():
    intent = resolve("copia el archivo", "es")
    assert round_trip(intent, "en") != round_trip(intent, "es")


def test_no_resuelto_pide_aclaracion_no_afirma():
    intent = resolve("copia", "es")
    frase = round_trip(intent, "es")
    assert "Entendí" not in frase
    assert "falta" in frase.lower() or "?" in frase
