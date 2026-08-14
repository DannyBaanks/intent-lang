import pytest
from intentlang import lexicon
from intentlang import propose as P


@pytest.fixture(scope="module", autouse=True)
def _instalar():
    lexicon.ensure_installed("es")


def test_el_lexico_descarta_lo_que_no_mapea():
    """'forzar' existe en espanol pero no mapea a primitiva -> se descarta."""
    validos = P.validate(["agregar", "insertar", "forzar", "qwertzuiop"], "es")
    assert "agregar" in validos
    assert "forzar" not in validos
    assert "qwertzuiop" not in validos


def test_el_modelo_no_puede_inventar_significado():
    """Aunque proponga algo inexistente, no sobrevive la validacion."""
    rec = P.propose("métele", "es", propose_fn=lambda s, l: ["flurbizar", "agregar"])
    assert rec.validated == ["agregar"]
    assert any(r["lemma"] == "flurbizar" for r in rec.rejected)


def test_la_cache_key_es_estable_y_completa():
    a = P.cache_key("métele", "es", "omw-es:1.4", "claude-opus-5")
    b = P.cache_key("métele", "es", "omw-es:1.4", "claude-opus-5")
    c = P.cache_key("métele", "es", "omw-es:1.4", "otro-modelo")
    assert a == b
    assert a != c


def test_llm_caido_degrada_a_strict_y_lo_escribe():
    def caido(surface, lang):
        raise RuntimeError("sin red")

    rec = P.propose("métele", "es", propose_fn=caido)
    assert rec.validated == []
    assert rec.degraded is not None
    assert "sin red" in rec.degraded
