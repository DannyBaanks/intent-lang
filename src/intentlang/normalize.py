"""Texto crudo -> lemas buscables.

Cada idioma declara su estrategia de tokenizacion en su YAML pack.
El dispatcher lee la estrategia del registry y delega.
"""
from __future__ import annotations

import re

from engine_lang.registry import registry

from .lexicon import UnsupportedLanguage, supported_languages

_PALABRA = re.compile(r"\w+", re.UNICODE)

_ja_tagger = None


def _ja_segmentar(text: str) -> list[str]:
    """Segmenta japones con fugashi/UniDic y devuelve LEMAS.

    UniDic da lemas tipo 'ファイル-file' (palabra + guion + lectura en ascii):
    se recorta la lectura para que el token coincida con los lemas de omw-ja.
    Si fugashi no esta instalado, falla duro: sin segmentador no hay japones.
    """
    global _ja_tagger
    if _ja_tagger is None:
        import fugashi
        _ja_tagger = fugashi.Tagger()
    out = []
    for t in _ja_tagger(text):
        lemma = t.feature.lemma or t.surface
        cortado = re.sub(r"-[a-z]+$", "", lemma)
        if _PALABRA.fullmatch(cortado):
            out.append(cortado)
    return out


def _kiwi_segmentar(text: str) -> list[str]:
    """Segmenta coreano con kiwipiepy y devuelve LEMAS."""
    import kiwipiepy
    kiwi = kiwipiepy.Kiwi()
    # Filtrar particles, endings, punctuation
    return [
        token.lemma
        for token in kiwi.tokenize(text)
        if token.tag.startswith(('NNG', 'NNP', 'VV', 'VA', 'VX', 'XSV', 'XSA'))
    ]


def _pymorphy3_lemmatize(text: str, lang: str) -> list[str]:
    """Lematiza ruso con pymorphy3."""
    import pymorphy3
    morph = pymorphy3.MorphAnalyzer(lang=lang)
    out = []
    for word in _PALABRA.findall(text.lower()):
        parsed = morph.parse(word)[0]
        out.append(parsed.normal_form)
    return out


def tokens(text: str, lang: str) -> list[str]:
    if lang not in supported_languages():
        raise UnsupportedLanguage(f"idioma no soportado en la v1: {lang!r}")

    strategy = registry().tokenizer_strategies.get(lang, "simplemma")

    if strategy == "jieba":
        import jieba
        return [t for t in jieba.lcut(text) if _PALABRA.fullmatch(t)]

    if strategy == "fugashi":
        return _ja_segmentar(text)

    if strategy == "kiwi":
        return _kiwi_segmentar(text)

    if strategy == "pymorphy3":
        return _pymorphy3_lemmatize(text, lang)

    # Default: simplemma (es, en, ar, fi, and any future simplemma language)
    import simplemma
    palabras = _PALABRA.findall(text.lower())
    return [simplemma.lemmatize(p, lang=lang) for p in palabras]


# Spanish imperative reconstruction table
_ES_IMPERATIVOS = {
    "copia": "copiar", "borra": "borrar", "graba": "grabar",
    "guarda": "guardar", "carga": "cargar", "descarga": "descargar",
    "imprime": "imprimir", "ejecuta": "ejecutar", "inicia": "iniciar",
    "termina": "terminar", "pausa": "pausar", "continua": "continuar",
    "reinicia": "reiniciar", "apaga": "apagar", "enciende": "encender",
    "abre": "abrir", "cierra": "cerrar", "crea": "crear",
    "edita": "editar", "modifica": "modificar", "elimina": "eliminar",
    "pega": "pegar", "corta": "cortar", "mueve": "mover",
    "renombra": "renombrar", "comprime": "comprimir",
    "descomprime": "descomprimir", "encripta": "encriptar",
    "desencripta": "desencriptar", "firma": "firmar",
    "verifica": "verificar", "valida": "validar",
    "importa": "importar", "exporta": "exportar",
    "sincroniza": "sincronizar", "respalda": "respaldar",
    "restaura": "restaurar",
}


def verb_candidates(lemma: str, lang: str) -> list[str]:
    """Lemas de verbo a probar para un token, en orden de preferencia.

    La reconstruccion es una PROPUESTA, no una afirmacion: quien decide si
    un lema existe sigue siendo la autoridad lexica.
    """
    candidatos = [lemma]
    strategy = registry().verb_strategies.get(lang, "none")

    if strategy == "es_imperative":
        infinitivo = _ES_IMPERATIVOS.get(lemma)
        if infinitivo:
            candidatos.append(infinitivo)

    if strategy == "ja_suru":
        # Solo agregar +する si el lema parece un verbo japones en hiragana (termina en u-row)
        # Verbos en forma diccionario terminan en: う, く, す, つ, む, る, ぶ, ぐ, ぬ
        # Katakana nouns (e.g. ファイル) terminan en katakana u-row pero NO son verbos
        hiragana_verb_endings = set("うくすつむるぶぐぬ")
        if lemma and lemma[-1] in hiragana_verb_endings:
            candidatos.append(lemma + "+する")

    # Custom verb candidates from YAML pack
    pack_candidates = registry().verb_candidates.get(lang, {})
    if lemma in pack_candidates:
        custom = pack_candidates[lemma]
        if custom not in candidatos:
            candidatos.append(custom)

    return candidatos
