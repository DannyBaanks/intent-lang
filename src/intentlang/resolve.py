"""Texto -> IR. Ensambla conceptos en intencion y decide el estado.

No adivina en ningun punto: si algo no resuelve, el estado lo dice y la IR no
puede actuar.
"""
from __future__ import annotations

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


def resolve(text: str, lang: str, mode: str = "strict") -> Intent:
    lemas = tokens(text, lang)
    prov = Provenance(
        surface=text, language=lang, lexical_source=source_id(lang),
        resolution="lexicon", confidence="exact", mode=mode,
    )

    verb, primitive, token_fuente = _first_verb(lemas, lang)
    if verb is None:
        return Intent(None, None, None, Status.UNKNOWN, prov)

    operand = _first_operand(lemas, lang, usado=token_fuente)
    if operand is None:
        return Intent(verb, None, None, Status.INCOMPLETE, prov, primitive=primitive)

    return Intent(verb, operand, None, Status.RESOLVED, prov, primitive=primitive)
