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


def verb_candidates(lemma: str, lang: str) -> list[str]:
    """Lemas de verbo a probar para un token, en orden de preferencia.

    Existe porque la lematizacion falla justo donde mas duele. `simplemma`
    resuelve bien casi todos los imperativos del espanol -- agrega->agregar,
    mueve->mover, elimina->eliminar, duplica->duplicar -- pero deja intactos
    `copia` y `borra`, porque tambien son sustantivos validos ("una copia",
    "la borra") y elige la lectura nominal. Con el lema sin cambiar no hay
    sentidos de verbo, y `resolve` devolveria UNKNOWN para "copia el archivo".
    `wn` tampoco ayuda: no indexa formas flexionadas.

    La reconstruccion es una PROPUESTA, no una afirmacion: quien decide si
    `copiar` existe y que significa sigue siendo la autoridad lexica. Un
    candidato inventado no encuentra sentidos y muere ahi. Es el mismo trato
    que recibe el proponente LLM -- propone, y el lexico dispone.
    """
    candidatos = [lemma]
    # Solo espanol: el ingles usa el infinitivo desnudo como imperativo
    # ("copy the file") y el chino no flexiona.
    if lang == "es" and len(lemma) > 2 and lemma.endswith("a"):
        candidatos.append(lemma + "r")   # copia -> copiar, borra -> borrar
    return candidatos
