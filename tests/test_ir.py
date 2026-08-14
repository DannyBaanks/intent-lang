import pytest
from intentlang.ir import Concept, Intent, Provenance, Status, PRIMITIVES


def prov(**kw):
    base = dict(surface="agrega cuerpo", language="es",
                lexical_source="omw-es:1.4", resolution="lexicon",
                confidence="exact", mode="strict")
    base.update(kw)
    return Provenance(**base)


def test_solo_resolved_puede_actuar():
    verb = Concept(ili="i35760", lemma="agregar")
    operand = Concept(ili="i52341", lemma="cuerpo")
    for status in Status:
        intent = Intent(verb=verb, operand=operand, scope=None,
                        status=status, provenance=prov())
        assert intent.can_act() is (status is Status.RESOLVED)


def test_hay_exactamente_ocho_primitivas():
    assert len(PRIMITIVES) == 8
    assert set(PRIMITIVES) == {"ADD", "REMOVE", "MOVE", "CHANGE",
                               "QUERY", "RUN", "COPY", "CONNECT"}


def test_provenance_es_obligatoria():
    with pytest.raises(TypeError):
        Intent(verb=None, operand=None, scope=None, status=Status.UNKNOWN)


def test_key_ignora_la_superficie():
    """Dos textos distintos con la misma semantica comparten key.

    `key()` es la identidad usada por la invariante de separacion: si dos
    intenciones DISTINTAS producen la misma key, el build se cae.
    """
    verb = Concept(ili="i35760", lemma="agregar")
    operand = Concept(ili="i52341", lemma="cuerpo")
    a = Intent(verb, operand, None, Status.RESOLVED, prov(surface="agrega cuerpo"))
    b = Intent(verb, operand, None, Status.RESOLVED, prov(surface="añade un cuerpo"))
    assert a.key() == b.key()
    assert a.provenance.surface != b.provenance.surface
