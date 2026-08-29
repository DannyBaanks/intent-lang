"""Autoridad lexica: que palabras existen y en que sentido.

Toda resolucion pasa por aca. Un lema que no esta en el wordnet de su idioma
no tiene sentido asignable, y punto: no se infiere, no se aproxima.

LEXICON_SOURCES se carga dinamicamente desde engine_lang/languages/*.yaml
via engine_lang.registry. No hardcodear idiomas aca.
"""
from __future__ import annotations

import functools

import wn

from engine_lang.registry import registry


def _get_lexicon_sources() -> dict[str, str]:
    return registry().wordnet_sources


class UnsupportedLanguage(Exception):
    """Idioma fuera de la v1. Falla cerrado: no se intenta otro wordnet."""


class LexiconUnavailable(Exception):
    """El wordnet del idioma no esta instalado. Error duro, no degradacion."""


def _ili_id(synset) -> str:
    """En wn 1.1.1 `synset.ili` es un str; en otras versiones un objeto con .id.

    Verificado en el spike: con wn 1.1.1 acceder a `.ili.id` revienta con
    AttributeError. Este helper tolera las dos formas.
    """
    v = synset.ili
    return getattr(v, "id", v)


def source_id(lang: str) -> str:
    try:
        return _get_lexicon_sources()[lang]
    except KeyError:
        raise UnsupportedLanguage(f"idioma no soportado en la v1: {lang!r}") from None


def supported_languages() -> list[str]:
    return registry().supported_languages


def ensure_installed(lang: str) -> None:
    """Descarga el wordnet si falta. Se llama explicitamente, nunca implicito."""
    pkg = source_id(lang)
    try:
        wn.Wordnet(pkg)
    except wn.Error:
        wn.download(pkg)


@functools.lru_cache(maxsize=8)
def _wordnet(lang: str) -> wn.Wordnet:
    pkg = source_id(lang)
    try:
        return wn.Wordnet(pkg)
    except wn.Error as exc:
        raise LexiconUnavailable(
            f"falta el wordnet {pkg}; correr ensure_installed({lang!r})") from exc


def senses(lemma: str, lang: str, pos: str | None = None) -> list[str]:
    """Ids ILI de los sentidos de `lemma`, EN EL ORDEN DE WORDNET.

    El orden es informacion, no ruido: WordNet lista los sentidos por
    frecuencia de uso, asi que el primero es el mas comun. Esta funcion
    devolvia `sorted(...)`, que ordena los ids alfabeticamente y tira esa
    informacion a la basura -- y como `resolve` toma `senses(...)[0]` para el
    operando, eso significaba elegir un sentido arbitrario.

    Medido: para `file` en ingles, WordNet ordena i70665, i81410, i53691,
    i53690; alfabeticamente el primero pasa a ser i53690. El sistema elegia el
    cuarto sentido mas frecuente creyendo que elegia el primero. En espanol
    `archivo` coincidia por casualidad (sus dos ids ya venian alfabeticos), y
    por eso ningun test lo noto.

    Se preserva el orden de aparicion y se deduplica sin reordenar.
    Lista vacia si el lema no esta en el lexico.
    """
    w = _wordnet(lang)
    vistos: list[str] = []
    for s in w.synsets(lemma, pos=pos):
        if not s.ili:
            continue
        ili = _ili_id(s)
        if ili not in vistos:
            vistos.append(ili)
    return vistos


@functools.lru_cache(maxsize=8)
def _build_ili_index(lang: str) -> dict[str, list[str]]:
    """Construye indice ili -> lemas para un idioma. Se cachea de una vez.

    Esto evita recorrer el wordnet entero en cada llamada a synonyms().
    """
    w = _wordnet(lang)
    index: dict[str, list[str]] = {}
    for synset in w.synsets():
        if synset.ili:
            ili = _ili_id(synset)
            if ili not in index:
                index[ili] = []
            index[ili].extend(synset.lemmas())
    # Convertir a listas ordenadas de lemas unicos
    for ili, lemas in index.items():
        index[ili] = sorted(set(lemas))
    return index


def synonyms(ili: str, lang: str) -> list[str]:
    """Lemas del synset, en `lang`. Es lo que alimenta el round-trip."""
    index = _build_ili_index(lang)
    return index.get(ili, [])