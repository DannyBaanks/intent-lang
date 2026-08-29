import pytest

from intentlang import lexicon
from intentlang.normalize import tokens


def test_espanol_lematiza_formas_conjugadas():
    assert "agregar" in tokens("agrégale un cuerpo", "es")
    assert "agregar" in tokens("agregando cuerpos", "es")


def test_ingles_lematiza():
    assert "add" in tokens("adding a body", "en")


def test_chino_segmenta_sin_espacios():
    resultado = tokens("添加身体", "zh")
    assert "添加" in resultado
    assert "身体" in resultado


def test_idioma_no_soportado_falla_cerrado():
    with pytest.raises(lexicon.UnsupportedLanguage):
        tokens("ajoute le corps", "fr")


def test_es_determinista():
    assert tokens("agrégale un cuerpo", "es") == tokens("agrégale un cuerpo", "es")
