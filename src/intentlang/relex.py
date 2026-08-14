"""IR -> frase en idioma humano.

No usa plantillas por idioma: toma el id ILI y elige una palabra del synset,
preferentemente DISTINTA a la que escribio el usuario. Esa diferencia es la
prueba de que la resolucion paso por el concepto y no por la cadena.
"""
from __future__ import annotations

from .ir import Concept, Intent, Status
from .lexicon import synonyms


DECLARED_OPERAND_PASSTHROUGH: dict[str, list[str]] = {
    "i50132": ["es"],  # archivo: OMW-es:1.4 tiene solo "archivo" como lema
    "i71104": ["es"],  # archivo (sentido 2): OMW-es:1.4 tiene solo "archivo" como lema
}


def _otra_palabra(concept: Concept, lang: str, evitar: str) -> str:
    if not concept.ili:
        return concept.lemma
    opciones = [s for s in synonyms(concept.ili, lang) if s != evitar]
    return opciones[0] if opciones else concept.lemma


def round_trip(intent: Intent, lang: str | None = None) -> str:
    lang = lang or intent.provenance.language

    if intent.status is Status.UNKNOWN:
        return "No reconocí ninguna intención en eso. ¿Podés decirlo de otra forma?"

    if intent.status is Status.INCOMPLETE:
        verbo = _otra_palabra(intent.verb, lang, intent.verb.lemma)
        return f"Falta sobre qué. ¿Qué {verbo}?"

    if intent.status is Status.AMBIGUOUS:
        if intent.candidates:
            opciones = " o ".join(c.upper() for c in intent.candidates)
            return f"¿Quisiste decir {opciones}?"
        else:
            return "No pude desambiguar la intención. ¿Podés ser más específico?"

    verbo = _otra_palabra(intent.verb, lang, intent.verb.lemma)
    objeto = _otra_palabra(intent.operand, lang, intent.operand.lemma)
    return f"Entendí: {verbo.upper()} ({objeto}). ¿Correcto?"
