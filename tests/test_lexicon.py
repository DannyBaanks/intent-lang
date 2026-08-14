import pytest
from intentlang import lexicon

ILI_COPIAR = "i30214"   # verificado en el spike: es/en/zh comparten este


@pytest.fixture(scope="module", autouse=True)
def _instalar():
    for lang in ("es", "en", "zh"):
        lexicon.ensure_installed(lang)


def test_el_mismo_concepto_converge_entre_idiomas():
    """Medido en el spike: copiar/copy/复制 comparten i30214."""
    es = set(lexicon.senses("copiar", "es", pos="v"))
    en = set(lexicon.senses("copy", "en", pos="v"))
    zh = set(lexicon.senses("复制", "zh", pos="v"))
    comun = es & en & zh
    assert comun, "sin ILI compartido no hay convergencia interlingue"
    assert ILI_COPIAR in comun


def test_lema_inexistente_devuelve_vacio_no_excepcion():
    assert lexicon.senses("qwertzuiop", "es") == []


def test_synset_da_sinonimos_para_el_round_trip():
    sinonimos = lexicon.synonyms(ILI_COPIAR, "es")
    assert "copiar" in sinonimos
    assert len(sinonimos) >= 2, "sin >=2 sinonimos el round-trip no puede variar la palabra"


def test_idioma_no_soportado_falla_cerrado():
    with pytest.raises(lexicon.UnsupportedLanguage):
        lexicon.senses("bonjour", "fr")


def test_source_id_es_verificable():
    assert lexicon.source_id("es") == "omw-es:1.4"
