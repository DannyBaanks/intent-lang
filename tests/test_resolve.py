import pytest
from intentlang import lexicon
from intentlang.ir import Status
from intentlang.resolve import resolve


@pytest.fixture(scope="module", autouse=True)
def _instalar():
    for lang in ("es", "en", "zh"):
        lexicon.ensure_installed(lang)


def test_verbo_y_operando_dan_resolved():
    intent = resolve("copia el archivo", "es")
    assert intent.status is Status.RESOLVED
    assert intent.primitive == "COPY"
    assert intent.can_act() is True


def test_sin_operando_da_incomplete_no_resolved():
    intent = resolve("copia", "es")
    assert intent.status is Status.INCOMPLETE
    assert intent.can_act() is False


def test_verbo_fuera_del_lexico_da_unknown():
    intent = resolve("qwertzuiop el archivo", "es")
    assert intent.status is Status.UNKNOWN
    assert intent.can_act() is False


def test_verbo_lexico_sin_primitiva_da_unknown():
    """'meter' existe en espanol pero no mapea a ninguna primitiva."""
    intent = resolve("métele un cuerpo", "es", mode="strict")
    assert intent.status is Status.UNKNOWN
    assert intent.can_act() is False


def test_provenance_completa_incluso_en_unknown():
    intent = resolve("qwertzuiop", "es")
    p = intent.provenance
    assert p.surface == "qwertzuiop"
    assert p.language == "es"
    assert p.lexical_source == "omw-es:1.4"
    assert p.mode == "strict"
    assert p.resolution == "lexicon"


def test_la_intencion_converge_entre_los_tres_idiomas():
    """La intencion converge. El operando NO, y eso esta medido, no asumido.

    El plan original pedia `es.key() == en.key() == zh.key()`. Los datos no
    lo permiten: `archivo`, `file` y `文件` no comparten NINGUN id ILI en
    omw-*:1.4 (es tiene i50132/i71104; en tiene i70665/i81410/i53691/i53690;
    zh tiene i36225/i70665/i70460 — interseccion vacia). No es un problema de
    ordenamiento: no hay sentido comun que elegir.

    La razon es estructural y vale mas que el test: el VERBO converge porque
    la tabla concepto->primitiva lo ancla a un unico ILI compartido. El
    operando es vocabulario libre, sin ancla, y la cobertura de sustantivos
    de OMW diverge entre idiomas. Convergencia exige ancla.

    Anclar operandos es exactamente lo que haria un dominio, y la v1 se
    declara sin dominio. Asi que aca se afirma lo que es cierto — la
    intencion converge — y se DEJA REGISTRADA la divergencia del operando en
    vez de borrarla del test.
    """
    es = resolve("copia el archivo", "es")
    en = resolve("copy the file", "en")
    zh = resolve("复制文件", "zh")

    assert es.status is Status.RESOLVED
    assert en.status is Status.RESOLVED
    assert zh.status is Status.RESOLVED

    # Lo que converge: la intencion.
    assert es.primitive == en.primitive == zh.primitive == "COPY"
    assert es.verb.ili == en.verb.ili == zh.verb.ili

    # Lo que no converge, y queda documentado: el operando.
    operandos = {es.operand.ili, en.operand.ili, zh.operand.ili}
    assert len(operandos) == 3, (
        "los operandos convergieron: si esto falla, la cobertura de OMW "
        "cambio y hay que revisar si el ancla de operandos ya no hace falta")
