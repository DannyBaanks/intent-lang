"""Texto -> IR. Ensambla conceptos en intencion y decide el estado.

No adivina en ningun punto: si algo no resuelve, el estado lo dice y la IR no
puede actuar.

Modo assisted: cuando la resolucion estricta da UNKNOWN, un proponente puede
sugerir lemas -- pero el lexico sigue siendo la unica autoridad. Ver
`_resolve_assisted` para las tres bifurcaciones de esa validacion.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Callable

from . import propose as _propose
from .ir import Concept, Intent, Provenance, Status
from .lexicon import senses, source_id
from .normalize import tokens, verb_candidates
from .primitives import primitive_for


def _first_verb(lemas: list[str], lang: str) -> tuple[Concept | None, str | None, str | None]:
    """Primer lema que resuelve a una primitiva.

    Devuelve `(concepto, primitiva, token_fuente)`. El token fuente importa:
    cuando el verbo se resolvio por reconstruccion (`copia` -> `copiar`), el
    operando tiene que descartar el token ORIGINAL, no el reconstruido. Sin
    eso, "copia el archivo" resuelve el verbo como `copiar` y despues elige
    `copia` -- el sustantivo -- como operando, en vez de `archivo`.
    """
    for lema in lemas:
        for candidato in verb_candidates(lema, lang):
            for ili in senses(candidato, lang, pos="v"):
                prim = primitive_for(ili)
                if prim:
                    return Concept(ili=ili, lemma=candidato), prim, lema
    return None, None, None


def _first_operand(lemas: list[str], lang: str, usado: str | None) -> Concept | None:
    """Primer sustantivo que no sea el token del que salio el verbo."""
    for lema in lemas:
        if lema == usado:
            continue
        ilis = senses(lema, lang, pos="n")
        if ilis:
            return Concept(ili=ilis[0], lemma=lema)
    return None


def resolve(text: str, lang: str, mode: str = "strict",
            propose_fn: Callable[[str, str], list[str]] | None = None) -> Intent:
    """Resuelve texto humano a IR canonica.

    `mode` se escribe en la provenance sin importar la rama que se tome; no
    se infiere nunca (§ restriccion global). El modo `strict` es 100%
    determinista y jamas invoca `propose_fn`, exista o no: eso solo puede
    pasar cuando `mode == "assisted"` Y `propose_fn` no es None Y la
    resolucion estricta dio UNKNOWN.
    """
    lemas = tokens(text, lang)
    prov = Provenance(
        surface=text, language=lang, lexical_source=source_id(lang),
        resolution="lexicon", confidence="exact", mode=mode,
    )

    verb, primitive, token_fuente = _first_verb(lemas, lang)
    if verb is None:
        if mode == "assisted" and propose_fn is not None:
            return _resolve_assisted(text, lang, lemas, prov, propose_fn)
        return Intent(None, None, None, Status.UNKNOWN, prov)

    operand = _first_operand(lemas, lang, usado=token_fuente)
    if operand is None:
        return Intent(verb, None, None, Status.INCOMPLETE, prov, primitive=primitive)

    return Intent(verb, operand, None, Status.RESOLVED, prov, primitive=primitive)


def _resolve_assisted(text: str, lang: str, lemas: list[str], prov: Provenance,
                       propose_fn: Callable[[str, str], list[str]]) -> Intent:
    """El proponente sugiere, el lexico valida, `resolve` decide el estado.

    El modelo nunca emite IR: `propose.propose()` ya redujo las sugerencias a
    lemas que el lexico confirmo. Aca solo se decide, segun CUANTOS
    sobrevivieron, entre reintentar (1), pedir aclaracion (>1) o quedarse en
    UNKNOWN (0) -- y en ese ultimo caso, propagar la degradacion si la hubo,
    nunca en silencio.
    """
    record = _propose.propose(text, lang, propose_fn)

    if len(record.validated) == 1:
        lema = record.validated[0]
        verb, primitive, token_fuente = _first_verb([lema], lang)
        operand = _first_operand(lemas, lang, usado=token_fuente)
        nueva_prov = replace(prov, resolution="llm_proposed+lexicon_validated",
                             confidence="proposed", cache_key=record.key)
        if operand is None:
            return Intent(verb, None, None, Status.INCOMPLETE, nueva_prov,
                          primitive=primitive)
        return Intent(verb, operand, None, Status.RESOLVED, nueva_prov,
                      primitive=primitive)

    if len(record.validated) > 1:
        nueva_prov = replace(prov, resolution="llm_proposed+lexicon_validated",
                             confidence="proposed", cache_key=record.key)
        return Intent(None, None, None, Status.AMBIGUOUS, nueva_prov,
                      candidates=tuple(record.validated))

    # 0 validados: sigue UNKNOWN. Si el proponente se cayo, la degradacion
    # queda escrita en provenance -- nunca en silencio.
    nueva_prov = prov if record.degraded is None else replace(prov, degraded=record.degraded)
    return Intent(None, None, None, Status.UNKNOWN, nueva_prov)
