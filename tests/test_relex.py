import pytest
from unittest.mock import patch
from intentlang import lexicon
from intentlang.relex import DECLARED_OPERAND_PASSTHROUGH, round_trip
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

    Este test cubre el efecto observable: que el passthrough sea visible en la
    frase, no silencioso. La verificación de que ese passthrough está declarado
    (y sólo ese) vive en test_declaracion_de_passthrough_operando_coincide_con_lo_medido,
    que mide TODAS las entradas declaradas, no sólo la que este resolve() ejercita.
    """
    intent = resolve("copia el archivo", "es")
    frase = round_trip(intent, "es")

    # El operando 'archivo' está presente sin cambios: esto es passthrough
    assert "archivo" in frase, f"El passthrough del operando debe ser visible: {frase!r}"

    # Pero el verbo SÍ cambió (RECREAR en lugar de COPIAR): la intención se resolvió
    assert intent.verb.lemma not in frase.lower(), f"El verbo debe tener sinónimo: {frase!r}"


def test_declaracion_de_passthrough_operando_coincide_con_lo_medido():
    """Simétrico con test_cada_concepto_existe_en_los_tres_idiomas (DECLARED_GAPS).

    El dominio medido NO se deriva de las claves de DECLARED_OPERAND_PASSTHROUGH
    (eso sería circular: borrar una entrada real la sacaría de ambos lados y el
    test nunca fallaría). Se deriva de forma independiente: los sentidos reales
    de "archivo" en OMW-es, vía lexicon.senses(). Así:

    - si un sentido declarado deja de ser passthrough (OMW le agrega un sinónimo,
      o el sentido desaparece), el medido difiere del declarado -> falla.
    - si aparece un sentido nuevo que hace passthrough y no está declarado,
      el medido lo incluye y el declarado no -> falla.

    Antes, el único assert de declaración (`intent.operand.ili in
    DECLARED_OPERAND_PASSTHROUGH`) sólo se ejercitaba con el ILI que devuelve
    UNA llamada a resolve("copia el archivo", "es"); i71104 nunca se medía.
    """
    ilis_archivo = lexicon.senses("archivo", "es", pos="n")

    medido: dict[str, list[str]] = {}
    for ili in ilis_archivo:
        alternativas = [s for s in lexicon.synonyms(ili, "es") if s != "archivo"]
        if not alternativas:
            medido[ili] = ["es"]

    if medido != DECLARED_OPERAND_PASSTHROUGH:
        todas_claves = set(DECLARED_OPERAND_PASSTHROUGH) | set(medido)
        sobra: dict[str, list[str]] = {}  # declarado pero ya no medido: hay que sacarlo
        falta: dict[str, list[str]] = {}  # medido pero no declarado: hay que agregarlo
        for k in todas_claves:
            declarado_v = set(DECLARED_OPERAND_PASSTHROUGH.get(k, []))
            medido_v = set(medido.get(k, []))
            solo_declarado = sorted(declarado_v - medido_v)
            solo_medido = sorted(medido_v - declarado_v)
            if solo_declarado:
                sobra[k] = solo_declarado
            if solo_medido:
                falta[k] = solo_medido
        pytest.fail(
            "DECLARED_OPERAND_PASSTHROUGH desactualizado respecto de lo medido.\n"
            f"  sobra en la declaración (ya no es passthrough real): {sobra}\n"
            f"  falta declarar (passthrough medido, no declarado): {falta}\n"
            f"  medido={medido!r} declarado={DECLARED_OPERAND_PASSTHROUGH!r}"
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
