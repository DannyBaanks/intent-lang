"""Signed Assisted Cache: caché firmado para propuestas asistidas.

Implementa el caché firmado que faltaba (NOT_IMPLEMENTED -> IMPLEMENTED).
Cada entrada de caché incluye:
- evidence_sha256: hash del evidence completo
- signature: firma criptográfica del cache entry
- timestamp: timestamp de creación
- proposer_model: modelo que propuso
- verified_by_lexicon: bool (validado por léxico)
- intent_ir: la IR resultante
- evidence: evidence completo del pipeline
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from .ir import Status


@dataclass(frozen=True, slots=True)
class CacheEntry:
    """Entrada de caché firmado para propuesta asistida."""
    # Identidad
    cache_key: str                    # sha256(surface + lang + lexicon + model)
    evidence_sha256: str              # sha256 del evidence completo
    
    # Metadatos
    timestamp: float                  # Unix timestamp
    proposer_model: str               # Modelo que propuso (ej: "claude-opus-5")
    surface: str                      # Texto original
    language: str                     # Código de idioma
    lexical_source: str               # WordNet package usado
    
    # Resultado
    intent_ir: dict                   # Intent.to_dict()
    evidence: dict                    # Evidence completo del pipeline
    
    # Validación
    verified_by_lexicon: bool         # True si lexicon validó la propuesta
    validated_lemmas: list[str]       # Lemas que sobrevivieron validación
    rejected_lemmas: list[dict]       # Lemas rechazados con razón
    
    # Firma criptográfica
    signature: str = ""               # Firma del entry (sha256 de todo lo anterior + secret)
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    def compute_content_hash(self) -> str:
        """Calcula hash del contenido (sin la firma)."""
        data = {
            "cache_key": self.cache_key,
            "evidence_sha256": self.evidence_sha256,
            "timestamp": self.timestamp,
            "proposer_model": self.proposer_model,
            "surface": self.surface,
            "language": self.language,
            "lexical_source": self.lexical_source,
            "intent_ir": self.intent_ir,
            "evidence": self.evidence,
            "verified_by_lexicon": self.verified_by_lexicon,
            "validated_lemmas": self.validated_lemmas,
            "rejected_lemmas": self.rejected_lemmas,
        }
        serialized = json.dumps(data, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    
    def sign(self, secret: str) -> CacheEntry:
        """Firma la entrada con un secreto compartido."""
        content_hash = self.compute_content_hash()
        signature = hashlib.sha256(f"{content_hash}{secret}".encode()).hexdigest()
        # Crear nueva instancia con firma (dataclass frozen)
        return replace(self, signature=signature)
    
    def verify_signature(self, secret: str) -> bool:
        """Verifica la firma."""
        expected = self.compute_content_hash()
        expected_sig = hashlib.sha256(f"{expected}{secret}".encode()).hexdigest()
        return self.signature == expected_sig


class SignedAssistedCache:
    """Caché de propuestas asistidas con firma y evidence_sha256."""
    
    def __init__(self, cache_dir: str | Path = ".intent_cache", secret: str = "intent-lang-secret"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.secret = secret
        self._index: dict[str, CacheEntry] = {}
        self._load_index()
    
    def _load_index(self) -> None:
        """Carga el índice de caché desde disco."""
        index_file = self.cache_dir / "index.json"
        if index_file.exists():
            try:
                data = json.loads(index_file.read_text(encoding="utf-8"))
                for key, entry_data in data.items():
                    self._index[key] = CacheEntry(**entry_data)
            except Exception:
                self._index = {}
    
    def _save_index(self) -> None:
        """Guarda el índice a disco."""
        index_file = self.cache_dir / "index.json"
        data = {k: v.to_dict() for k, v in self._index.items()}
        index_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    
    def _cache_key(self, surface: str, language: str, lexical_source: str, model: str) -> str:
        """Genera cache key determinista."""
        material = f"{surface}\x1f{language}\x1f{lexical_source}\x1f{model}"
        return "sha256:" + hashlib.sha256(material.encode("utf-8")).hexdigest()
    
    def _evidence_sha256(self, evidence: dict) -> str:
        """Calcula SHA256 del evidence completo."""
        serialized = json.dumps(evidence, sort_keys=True, ensure_ascii=False)
        return "sha256:" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    
    def get(self, surface: str, language: str, model: str = "default") -> CacheEntry | None:
        """Obtiene entrada de caché si existe y firma es válida."""
        from .lexicon import source_id
        
        lexical_source = source_id(language)
        key = self._cache_key(surface, language, lexical_source, model)
        
        entry = self._index.get(key)
        if entry and entry.verify_signature(self.secret):
            return entry
        return None
    
    def put(self, surface: str, language: str, model: str, 
            intent_ir: dict, evidence: dict, 
            validated_lemmas: list[str], rejected_lemmas: list[dict],
            verified_by_lexicon: bool) -> CacheEntry:
        """Almacena una nueva entrada en caché."""
        from .lexicon import source_id
        
        lexical_source = source_id(language)
        key = self._cache_key(surface, language, lexical_source, model)
        evidence_sha = self._evidence_sha256(evidence)
        
        entry = CacheEntry(
            cache_key=key,
            evidence_sha256=evidence_sha,
            timestamp=time.time(),
            proposer_model=model,
            surface=surface,
            language=language,
            lexical_source=lexical_source,
            intent_ir=intent_ir,
            evidence=evidence,
            verified_by_lexicon=verified_by_lexicon,
            validated_lemmas=validated_lemmas,
            rejected_lemmas=rejected_lemmas,
            signature="",  # se firma abajo
        )
        
        # Firmar
        signed_entry = entry.sign(self.secret)
        self._index[key] = signed_entry
        self._save_index()
        return signed_entry
    
    def get_or_compute(self, surface: str, language: str, model: str,
                       propose_fn, lexicon_validate_fn) -> tuple[CacheEntry, bool]:
        """Obtiene de caché o computa y almacena.
        
        Returns: (CacheEntry, from_cache)
        """
        from .lexicon import source_id
        from .propose import propose
        
        lexical_source = source_id(language)
        
        # Intentar obtener de caché
        cached = self.get(surface, language, model)
        if cached:
            return cached, True
        
        # No está en caché: proponer y validar
        proposal = propose(surface, language, propose_fn, model)
        
        # Construir evidence
        evidence = {
            "surface": surface,
            "language": language,
            "proposal": {
                "proposed": proposal.proposed,
                "validated": proposal.validated,
                "rejected": proposal.rejected,
                "degraded": proposal.degraded,
            },
            "lexicon_validation": {
                "verified_by_lexicon": len(proposal.validated) > 0,
                "validated_lemmas": proposal.validated,
                "rejected_lemmas": proposal.rejected,
            },
            "cache_key": self._cache_key(surface, language, lexical_source, model),
        }
        
        intent_ir = {
            "status": "RESOLVED" if proposal.validated else "UNKNOWN",
            "primitive": "UNKNOWN",  # Se llenaría con resolve real
            "validated_lemmas": proposal.validated,
        }
        
        entry = self.put(
            surface=surface,
            language=language,
            model=model,
            intent_ir=intent_ir,
            evidence=evidence,
            validated_lemmas=proposal.validated,
            rejected_lemmas=proposal.rejected,
            verified_by_lexicon=len(proposal.validated) > 0,
        )
        
        return entry, False
    
    def list_entries(self) -> list[CacheEntry]:
        return list(self._index.values())
    
    def clear(self) -> None:
        self._index.clear()
        self._save_index()


# Instancia global
_global_cache: SignedAssistedCache | None = None


def get_assisted_cache(cache_dir: str | Path = ".intent_cache", secret: str = "intent-lang-secret") -> SignedAssistedCache:
    global _global_cache
    if _global_cache is None:
        _global_cache = SignedAssistedCache(cache_dir, secret)
    return _global_cache


def cached_assisted_resolve(surface: str, language: str, model: str = "default",
                            propose_fn=None) -> tuple[dict, bool]:
    """Resolve asistido con caché firmado.
    
    Returns: (intent_dict, from_cache)
    """
    cache = get_assisted_cache()
    
    # Buscar en caché
    cached = cache.get(surface, language, model)
    if cached is not None:
        return cached.intent_ir, True
    
    # No está en caché: resolver y guardar
    from .resolve import resolve
    intent = resolve(surface, language, mode="assisted", propose_fn=propose_fn)
    intent_dict = intent.to_dict()
    
    # Guardar en caché con evidencia
    evidence = {
        "surface": surface,
        "language": language,
        "model": model,
        "intent_primitive": intent.primitive,
        "intent_status": intent.status.value if intent.status else None,
    }
    # verified_by_lexicon es evidencia, no decoración: solo RESOLVED lo está
    verified_by_lexicon = intent.status == Status.RESOLVED
    cache.put(
        surface=surface,
        language=language,
        model=model,
        intent_ir=intent_dict,
        evidence=evidence,
        validated_lemmas=[],
        rejected_lemmas=[],
        verified_by_lexicon=verified_by_lexicon,
    )
    
    return intent_dict, False