"""Texto crudo -> lemas buscables.

Espanol e ingles se lematizan; chino se segmenta (no tiene flexion ni espacios).
Agregar un idioma es agregar una entrada aca y su wordnet en lexicon.py: el
runtime no se toca.
"""
from __future__ import annotations

import re

import jieba
import simplemma

from .lexicon import LEXICON_SOURCES, UnsupportedLanguage

_PALABRA = re.compile(r"\w+", re.UNICODE)


def tokens(text: str, lang: str) -> list[str]:
    if lang not in LEXICON_SOURCES:
        raise UnsupportedLanguage(f"idioma no soportado en la v1: {lang!r}")

    if lang == "zh":
        # jieba corta la cadena; se descarta la puntuacion.
        return [t for t in jieba.lcut(text) if _PALABRA.fullmatch(t)]

    palabras = _PALABRA.findall(text.lower())
    return [simplemma.lemmatize(p, lang=lang) for p in palabras]
