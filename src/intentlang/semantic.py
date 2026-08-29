"""Semantic Capability Interface: backends pluggables para semántica.

WordNet deja de ser dependencia arquitectónica; es solo UN backend más.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from .lexicon import UnsupportedLanguage


@dataclass(frozen=True, slots=True)
class SemanticResult:
    """Resultado estandarizado de lookup semántico."""
    word: str
    language: str
    backend: str
    senses: list[dict]  # cada sense: {"ili": str, "lemma": str, "pos": str, "definition": str}
    confidence: float = 1.0


@dataclass(frozen=True, slots=True)
class SimilarityResult:
    """Resultado de similitud semántica."""
    word_a: str
    word_b: str
    language: str
    backend: str
    score: float  # 0.0 - 1.0
    method: str


class SemanticCapability(ABC):
    """Interfaz que debe implementar cualquier backend semántico."""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Nombre único del backend (ej: 'wordnet', 'korean', 'thai')."""
    
    @property
    @abstractmethod
    def supported_languages(self) -> set[str]:
        """Códigos ISO que soporta este backend."""
    
    @abstractmethod
    def supports(self, language: str) -> bool:
        """¿Soporta este idioma?"""
    
    @abstractmethod
    def lookup(self, word: str, language: str, pos: str | None = None) -> SemanticResult:
        """Busca sentidos de una palabra. Lanza UnsupportedLanguage si no soporta el idioma."""
    
    @abstractmethod
    def similarity(self, word_a: str, word_b: str, language: str) -> SimilarityResult:
        """Similitud semántica entre dos palabras."""
    
    @abstractmethod
    def relations(self, word: str, language: str, relation_type: str | None = None) -> list[dict]:
        """Relaciones semánticas (hypernym, hyponym, meronym, etc.)."""


class UnsupportedLanguageError(UnsupportedLanguage):
    """Idioma no soportado por ningún backend semántico."""


class SemanticRouter:
    """Enruta peticiones al backend correcto según idioma.
    
    No hay if/else por idioma: los backends se registran y declaran
    qué idiomas soportan. El router elige el primero que soporte el idioma.
    """
    
    def __init__(self):
        self._backends: list[SemanticCapability] = []
    
    def register(self, backend: SemanticCapability) -> None:
        """Registra un backend. Orden = prioridad (primero gana)."""
        self._backends.append(backend)
    
    def _find_backend(self, language: str) -> SemanticCapability:
        for backend in self._backends:
            if backend.supports(language):
                return backend
        raise UnsupportedLanguageError(f"No semantic backend for language: {language}")
    
    def lookup(self, word: str, language: str, pos: str | None = None) -> SemanticResult:
        backend = self._find_backend(language)
        return backend.lookup(word, language, pos)
    
    def similarity(self, word_a: str, word_b: str, language: str) -> SimilarityResult:
        backend = self._find_backend(language)
        return backend.similarity(word_a, word_b, language)
    
    def relations(self, word: str, language: str, relation_type: str | None = None) -> list[dict]:
        backend = self._find_backend(language)
        return backend.relations(word, language, relation_type)
    
    def get_backend_for(self, language: str) -> str:
        """Devuelve nombre del backend que maneja el idioma."""
        return self._find_backend(language).name
    
    def list_supported_languages(self) -> set[str]:
        """Union de todos los idiomas soportados por backends registrados."""
        langs = set()
        for b in self._backends:
            langs.update(b.supported_languages)
        return langs


# ============================================================
# Backend WordNet (existente, envuelto en la interfaz)
# ============================================================

class WordNetSemantic(SemanticCapability):
    """Wrapper del WordNet existente."""
    
    @property
    def name(self) -> str:
        return "wordnet"
    
    @property
    def supported_languages(self) -> set[str]:
        # Los que tienen wordnet instalado y funcionando
        from .lexicon import supported_languages
        return set(supported_languages())
    
    def supports(self, language: str) -> bool:
        return language in self.supported_languages
    
    def lookup(self, word: str, language: str, pos: str | None = None) -> SemanticResult:
        from .lexicon import senses, synonyms
        
        if not self.supports(language):
            raise UnsupportedLanguageError(f"WordNet no soporta: {language}")
        
        ili_list = senses(word, language, pos=pos)
        senses_data = []
        for ili in ili_list:
            syns = synonyms(ili, language)
            senses_data.append({
                "ili": ili,
                "lemma": syns[0] if syns else word,
                "pos": pos or "unknown",
                "definition": "",  # WordNet no da definiciones fácil
            })
        
        return SemanticResult(
            word=word,
            language=language,
            backend=self.name,
            senses=senses_data,
        )
    
    def similarity(self, word_a: str, word_b: str, language: str) -> SimilarityResult:
        """Similitud simple: comparten algún ILI?"""
        from .lexicon import senses
        
        if not self.supports(language):
            raise UnsupportedLanguageError(f"WordNet no soporta: {language}")
        
        senses_a = set(senses(word_a, language, pos="n"))
        senses_b = set(senses(word_b, language, pos="n"))
        
        shared = senses_a & senses_b
        score = 1.0 if shared else 0.0
        
        return SimilarityResult(
            word_a=word_a,
            word_b=word_b,
            language=language,
            backend=self.name,
            score=score,
            method="ili_overlap",
        )
    
    def relations(self, word: str, language: str, relation_type: str | None = None) -> list[dict]:
        # Placeholder: WordNet relations son complejas de extraer
        return []


# ============================================================
# Registry global y router singleton
# ============================================================

_global_router: SemanticRouter | None = None


def get_semantic_router() -> SemanticRouter:
    global _global_router
    if _global_router is None:
        _global_router = SemanticRouter()
        # Registrar WordNet por defecto
        _global_router.register(WordNetSemantic())
    return _global_router


def register_semantic_backend(backend: SemanticCapability) -> None:
    """Registra un nuevo backend semántico (ej: KoreanSemantic)."""
    router = get_semantic_router()
    router.register(backend)


def lookup_semantic(word: str, language: str, pos: str | None = None) -> SemanticResult:
    """Entry point: lookup semántico con router automático."""
    return get_semantic_router().lookup(word, language, pos)


def semantic_similarity(word_a: str, word_b: str, language: str) -> SimilarityResult:
    return get_semantic_router().similarity(word_a, word_b, language)


def get_semantic_backend(language: str) -> str:
    """¿Qué backend maneja este idioma?"""
    return get_semantic_router().get_backend_for(language)


def list_supported_semantic_languages() -> set[str]:
    return get_semantic_router().list_supported_languages()