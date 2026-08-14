import pytest
from intentlang import lexicon
from intentlang import propose as _propose
from intentlang.ir import Status
from intentlang.relex import round_trip
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


# --- Rama assisted: hueco del plan (Tarea 8), resuelto por decisión explícita. ---
# resolve(text, lang, mode="strict", propose_fn=None). Sólo cuando la
# resolución estricta da UNKNOWN Y mode=="assisted" Y propose_fn no es None
# se invoca propose.propose(). Estos tests cubren las tres bifurcaciones del
# resultado de validate() (1 / >1 / 0 candidatos) más los dos gates (modo,
# propose_fn ausente) que deben dejar el comportamiento strict intacto.

def test_assisted_con_un_lema_valido_reintenta_y_resuelve():
    """'meter' no mapea a primitiva; el proponente ofrece 'agregar', el
    lexico lo valida, y la resolucion se reintenta con ese lema."""
    intent = resolve("métele un cuerpo", "es", mode="assisted",
                     propose_fn=lambda s, l: ["agregar"])

    assert intent.status is Status.RESOLVED
    assert intent.can_act() is True
    assert intent.primitive == "ADD"
    assert intent.verb.lemma == "agregar"
    assert intent.operand.lemma == "cuerpo"

    p = intent.provenance
    assert p.mode == "assisted"
    assert p.resolution == "llm_proposed+lexicon_validated"
    assert p.confidence == "proposed"
    # La cache_key no es solo "no-None": tiene que ser LA MISMA que produce
    # propose.cache_key con los mismos insumos. Si resolve() la inventara o
    # la truncara, esta igualdad puntual fallaria.
    esperado = _propose.cache_key("métele un cuerpo", "es",
                                  lexicon.source_id("es"), "claude-opus-5")
    assert p.cache_key == esperado


def test_assisted_con_dos_lemas_validos_da_ambiguous_con_candidatos_reales():
    """'agregar' y 'añadir' comparten primitiva ADD: ambos sobreviven la
    validacion, y eso es exactamente lo que hace alcanzable AMBIGUOUS por
    primera vez -- antes era codigo muerto en round_trip()."""
    intent = resolve("métele un cuerpo", "es", mode="assisted",
                     propose_fn=lambda s, l: ["agregar", "añadir"])

    assert intent.status is Status.AMBIGUOUS
    assert intent.can_act() is False
    assert set(intent.candidates) == {"agregar", "añadir"}

    frase = round_trip(intent, "es")
    assert not frase.startswith("Entendí"), f"AMBIGUOUS no debe afirmar: {frase!r}"
    assert "AGREGAR" in frase and "AÑADIR" in frase, (
        f"el mensaje de aclaracion debe mostrar los candidatos reales: {frase!r}")


def test_assisted_sin_candidatos_validos_sigue_unknown_sin_degradar():
    """Ambos lemas propuestos existen o no, pero ninguno sobrevive la
    validacion lexica -> sigue UNKNOWN, y sin degraded (el proponente SI
    corrio, solo que no encontro nada util -- eso no es una degradacion)."""
    intent = resolve("métele un cuerpo", "es", mode="assisted",
                     propose_fn=lambda s, l: ["flurbizar", "forzar"])

    assert intent.status is Status.UNKNOWN
    assert intent.can_act() is False
    assert intent.provenance.degraded is None


def test_assisted_proponente_caido_degrada_y_lo_escribe_en_provenance():
    """Si el proponente revienta, resolve() falla cerrado (UNKNOWN) y la
    degradacion queda escrita en provenance.degraded, nunca silenciosa."""
    def caido(surface, lang):
        raise RuntimeError("sin red")

    intent = resolve("métele un cuerpo", "es", mode="assisted", propose_fn=caido)

    assert intent.status is Status.UNKNOWN
    assert intent.provenance.mode == "assisted"
    assert intent.provenance.degraded is not None
    assert "sin red" in intent.provenance.degraded


def test_modo_strict_nunca_invoca_al_proponente():
    """El modo strict no cambia de comportamiento aunque se le pase
    propose_fn: nunca deberia ejecutarlo. Se mide con un contador real, no
    con la ausencia de crash."""
    llamadas = []

    def contador(surface, lang):
        llamadas.append((surface, lang))
        return ["agregar"]

    intent = resolve("métele un cuerpo", "es", mode="strict", propose_fn=contador)

    assert intent.status is Status.UNKNOWN
    assert llamadas == [], "strict invoco al proponente: eso no es strict"
    assert intent.provenance.resolution == "lexicon"
    assert intent.provenance.cache_key is None


def test_assisted_sin_propose_fn_no_intenta_nada():
    """mode='assisted' solo no alcanza: sin propose_fn, el gate se queda
    cerrado y el resultado es identico al strict."""
    intent = resolve("métele un cuerpo", "es", mode="assisted")

    assert intent.status is Status.UNKNOWN
    assert intent.provenance.resolution == "lexicon"
    assert intent.provenance.cache_key is None
