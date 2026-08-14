import pytest
from unittest.mock import patch
from intentlang import lexicon
from intentlang.relex import round_trip
from intentlang.resolve import resolve
from intentlang.ir import Intent, Status, Concept, Provenance


def prov(**kw):
    """Helper para crear Provenance en tests."""
    base = dict(surface="copia la foto", language="es",
                lexical_source="omw-es:1.4", resolution="lexicon",
                confidence="exact", mode="strict")
    base.update(kw)
    return Provenance(**base)


@pytest.fixture(scope="module", autouse=True)
def _instalar():
    for lang in ("es", "en", "zh"):
        lexicon.ensure_installed(lang)


def test_usa_una_palabra_DISTINTA_a_la_del_usuario():
    """El test que convierte el round-trip en deteccion de fraude.

    Si devuelve exactamente la palabra escrita, la capa semantica no corrio
    y estamos viendo un passthrough de strings. Usa "copia la foto" para que
    tanto verbo como operando tengan sinónimos disponibles.
    """
    intent = resolve("copia la foto", "es")
    frase = round_trip(intent, "es")
    # El verbo se uppercasea, así que buscar contra el lemma en mayúsculas detecta passthrough real
    assert intent.verb.lemma.upper() not in frase, f"passthrough de strings en verbo: {frase!r}"
    # El operando no se uppercasea, así que este assert sí funciona de verdad
    assert intent.operand.lemma not in frase, f"passthrough de strings en operando: {frase!r}"


def test_passthrough_del_verbo_se_detecta():
    """Si forzamos que synonyms() devuelva lista vacía (passthrough total),
    el assert del verbo debe FALLAR. Esto valida que el test de arriba no es vacuo.
    """
    intent = resolve("copia la foto", "es")

    # Monkeypatch synonyms para que devuelva lista vacía (fuerza passthrough)
    with patch("intentlang.relex.synonyms") as mock_synonyms:
        mock_synonyms.return_value = []
        frase = round_trip(intent, "es")

        # El test debería fallar porque "COPIAR" estará en la frase
        try:
            assert intent.verb.lemma.upper() not in frase
            # Si llegamos aquí, el test fue vacuo (no detectó el passthrough)
            pytest.fail("El test no detectó passthrough: el assert no falló como se esperaba")
        except AssertionError:
            # Esto es lo que queremos: que el assert falle cuando hay passthrough
            pass


def test_operando_passthrough_cuando_sin_sinonimos():
    """El operando hace passthrough cuando OMW no tiene sinónimos.

    Para "archivo" (i50132, i71104), ambos sentidos en OMW tienen solo "archivo"
    como lema en español. Esto es una limitación estructural de la cobertura de OMW,
    no un error del sistema. _otra_palabra() cae al lemma original por diseño
    cuando synonyms() devuelve lista con un solo elemento (el lemma actual).

    Este test compara lo MEDIDO (qué operandos hacen passthrough de verdad) contra
    lo DECLARADO (DECLARED_OPERAND_PASSTHROUGH). Si algún día OMW agrega sinónimos,
    este test detectará que el passthrough se cerró y habrá que actualizar la declaración.
    """
    from intentlang.relex import DECLARED_OPERAND_PASSTHROUGH

    intent = resolve("copia el archivo", "es")
    frase = round_trip(intent, "es")

    # El operando 'archivo' está presente sin cambios: esto es passthrough
    assert "archivo" in frase, f"El passthrough del operando debe ser visible: {frase!r}"

    # Pero el verbo SÍ cambió (RECREAR en lugar de COPIAR): la intención se resolvió
    assert intent.verb.lemma not in frase.lower(), f"El verbo debe tener sinónimo: {frase!r}"

    # Verificar que el passthrough está declarado. Si el test falla aquí, significa
    # que OMW agregó sinónimos y hay que actualizar DECLARED_OPERAND_PASSTHROUGH.
    assert intent.operand.ili in DECLARED_OPERAND_PASSTHROUGH, (
        f"passthrough del operando i{intent.operand.ili} no está declarado en "
        f"DECLARED_OPERAND_PASSTHROUGH. Si OMW agregó sinónimos, actualizar la "
        f"constante. Si es un operando nuevo, agregarlo a la declaración."
    )
    assert "es" in DECLARED_OPERAND_PASSTHROUGH[intent.operand.ili], (
        f"passthrough del operando i{intent.operand.ili} en español no está declarado"
    )


def test_puede_devolver_en_otro_idioma():
    intent = resolve("copia el archivo", "es")
    assert round_trip(intent, "en") != round_trip(intent, "es")


def test_no_resuelto_pide_aclaracion_no_afirma():
    intent = resolve("copia", "es")
    frase = round_trip(intent, "es")
    assert "Entendí" not in frase
    assert "falta" in frase.lower() or "?" in frase


def test_ambiguous_con_candidatos():
    """Status.AMBIGUOUS pide aclaración sin afirmar comprensión."""
    verbo = Concept(ili="i2561", lemma="copiar")
    operando = Concept(ili="i50132", lemma="archivo")

    intent = Intent(
        verb=verbo,
        operand=operando,
        scope=None,
        status=Status.AMBIGUOUS,
        provenance=prov(),
        primitive="ADD",
        candidates=("COPY", "DUPLICATE")
    )

    frase = round_trip(intent, "es")
    # No afirmar: no debe empezar con "Entendí"
    assert not frase.startswith("Entendí"), f"AMBIGUOUS no debe afirmar: {frase!r}"
    # Pedir aclaración: debe mencionar los candidatos
    assert "COPY" in frase or "DUPLICATE" in frase, f"AMBIGUOUS debe mostrar candidatos: {frase!r}"


def test_ambiguous_sin_candidatos():
    """Si candidates está vacío, devolver mensaje sensato (no "¿Quisiste decir ?")."""
    verbo = Concept(ili="i2561", lemma="copiar")
    operando = Concept(ili="i50132", lemma="archivo")

    intent = Intent(
        verb=verbo,
        operand=operando,
        scope=None,
        status=Status.AMBIGUOUS,
        provenance=prov(),
        primitive="ADD",
        candidates=()  # vacío
    )

    frase = round_trip(intent, "es")
    # No debe producir "¿Quisiste decir ?" (frase rota)
    assert "¿Quisiste decir ?" not in frase, f"Frase rota con candidates vacío: {frase!r}"
    # Debe tener un mensaje sensato
    assert len(frase) > 0, "Respuesta vacía"
