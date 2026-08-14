"""Autoridad lexica: que palabras existen y en que sentido.

Toda resolucion pasa por aca. Un lema que no esta en el wordnet de su idioma
no tiene sentido asignable, y punto: no se infiere, no se aproxima.
"""
from __future__ import annotations

import functools

import wn

LEXICON_SOURCES: dict[str, str] = {
    "es": "omw-es:1.4",
    "en": "omw-en:1.4",
    "zh": "omw-cmn:1.4",
}


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
        return LEXICON_SOURCES[lang]
    except KeyError:
        raise UnsupportedLanguage(f"idioma no soportado en la v1: {lang!r}") from None


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
    """Ids ILI de los sentidos de `lemma`. Lista vacia si no esta en el lexico."""
    w = _wordnet(lang)
    return sorted({_ili_id(s) for s in w.synsets(lemma, pos=pos) if s.ili})


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
    for ili in index:
        index[ili] = sorted(set(index[ili]))
    return index


def synonyms(ili: str, lang: str) -> list[str]:
    """Lemas del synset, en `lang`. Es lo que alimenta el round-trip."""
    index = _build_ili_index(lang)
    return index.get(ili, [])
