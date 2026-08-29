"""Proponente gateado: el modelo propone, el lexico dispone.

Nunca emite IR. Devuelve lemas candidatos que la autoridad lexica valida; lo
que no existe en el wordnet, o existe pero no mapea a primitiva, se descarta
sin apelacion. Por eso "no inventa significado" es estructural.
"""
from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass

from .lexicon import senses, source_id
from .primitives import primitive_for


@dataclass(frozen=True, slots=True)
class ProposalRecord:
    key: str
    proposed: list[str]
    validated: list[str]
    rejected: list[dict]
    degraded: str | None = None


def cache_key(surface: str, lang: str, lexicon_id: str, model: str) -> str:
    """Identidad completa de la propuesta: si algo de esto cambia, es otro hecho."""
    material = f"{surface}\x1f{lang}\x1f{lexicon_id}\x1f{model}"
    return "sha256:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def validate(candidates: list[str], lang: str) -> list[str]:
    """Sobreviven solo los lemas que existen Y mapean a una primitiva."""
    return [
        lema
        for lema in candidates
        if any(primitive_for(ili) for ili in senses(lema, lang, pos="v"))
    ]


def propose(surface: str, lang: str,
            propose_fn: Callable[[str, str], list[str]],
            model: str = "claude-opus-5") -> ProposalRecord:
    key = cache_key(surface, lang, source_id(lang), model)

    try:
        candidatos = list(propose_fn(surface, lang))
    except Exception as exc:
        # Falla cerrado: sin propuestas, y la degradacion queda escrita.
        return ProposalRecord(key=key, proposed=[], validated=[], rejected=[],
                              degraded=f"proponente no disponible: {exc}")

    validos = validate(candidatos, lang)
    rechazados = [{"lemma": c, "reason": "no existe o no mapea a primitiva"}
                  for c in candidatos if c not in validos]
    return ProposalRecord(key=key, proposed=candidatos,
                          validated=validos, rejected=rechazados)
