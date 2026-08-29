from engine_lang.registry import registry
from intentlang import primitives
from intentlang.ir import PRIMITIVES

LANGS = registry().supported_languages
LANGS_WN = registry().languages_with_wordnet


def test_toda_entrada_apunta_a_una_primitiva_valida():
    for ili, prim in primitives.load_map().items():
        assert prim in PRIMITIVES, f"{ili} apunta a {prim!r}, que no es primitiva"


def test_la_tabla_respeta_su_techo():
    """Techo duro de la spec: pasarlo significa que falta un dominio."""
    assert len(primitives.load_map()) <= primitives.MAX_ENTRIES


def test_concepto_sin_mapeo_devuelve_none_no_adivina():
    assert primitives.primitive_for("i-que-no-existe") is None


def test_las_ocho_primitivas_tienen_al_menos_un_concepto():
    # Solo las 8 primitivas v1 original; las nuevas familias no requieren concepto en concept_map
    PRIMITIVES_V1 = {"ADD", "REMOVE", "MOVE", "CHANGE", "QUERY", "RUN", "COPY", "CONNECT"}
    cubiertas = set(primitives.load_map().values())
    faltan = PRIMITIVES_V1 - cubiertas
    assert not faltan, f"primitivas v1 sin concepto que las alcance: {faltan}"


def test_cada_concepto_existe_en_los_tres_idiomas():
    """La cobertura por idioma tiene que ser explicita, nunca silenciosa.

    Sin este test, un hablante de chino recibiria UNKNOWN para una intencion
    que en espanol resuelve, y el sistema no sabria por que. Un hueco declarado
    no es un hueco escondido.
    """
    from intentlang import lexicon
    for lang in LANGS_WN:
        lexicon.ensure_installed(lang)

    huecos = {}
    for ili in primitives.load_map():
        faltan = [lang for lang in LANGS_WN if not lexicon.synonyms(ili, lang)]
        if faltan:
            huecos[ili] = faltan

    assert huecos == primitives.DECLARED_GAPS, (
        f"cobertura por idioma cambio: medido {huecos}, declarado "
        f"{primitives.DECLARED_GAPS}. Actualizar DECLARED_GAPS a proposito, "
        "no por inercia.")


def test_ADD_declara_su_hueco_en_chino():
    """omw-cmn:1.4 no tiene i22623. Medido en el spike con 6 lemas chinos."""
    assert "zh" in primitives.DECLARED_GAPS.get("i22623", [])
