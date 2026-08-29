"""Representacion canonica de intencion: sin idioma, con procedencia completa."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum

# ============================================================
# PRIMITIVAS: tres familias composables
# ============================================================

PRIMITIVES_EFFECTS: tuple[str, ...] = (
    # Originales v1
    "ADD", "REMOVE", "MOVE", "CHANGE", "QUERY", "RUN", "COPY", "CONNECT",
    # Efectos extendidos (capabilities filesystem, network, process, crypto, media)
    "DOWNLOAD", "COMPILE", "RENDER", "SIGN", "WRITE", "READ", "DELETE",
    "EXECUTE", "ARCHIVE", "EXTRACT", "ENCRYPT", "DECRYPT",
)

PRIMITIVES_DATA: tuple[str, ...] = (
    "VALUE",      # literal / constant
    "BIND",       # let x = ...
    "LOAD",       # load from source
    "STORE",      # store to target
    "COMPARE",    # eq/lt/gt/contains
    "MAP",        # transform each
    "FILTER",     # keep if
    "COLLECT",    # aggregate
    "REDUCE",     # fold
    "PROJECT",    # select fields
    "JOIN",       # combine streams
    "SORT",       # order
    "GROUP",      # group by key
    "REFERENCE",  # reference a binding
)

PRIMITIVES_CONTROL: tuple[str, ...] = (
    "SEQUENCE",   # A; B
    "IF",         # cond -> then : else
    "LOOP",       # while / for-each
    "CALL",       # invoke capability
    "RETURN",     # yield value
    "MATCH",      # pattern match
    "ASSERT",     # precondition
    "TRY",        # try/catch/result
    "PARALLEL",   # concurrent execution
    "FOREACH",    # iterate collection
    "TRANSACTION", # execute with explicit rollback scope
)

ALL_PRIMITIVES: tuple[str, ...] = PRIMITIVES_EFFECTS + PRIMITIVES_DATA + PRIMITIVES_CONTROL

PRIMITIVES: tuple[str, ...] = ALL_PRIMITIVES  # compatibilidad v1


# ============================================================
# CLASES EXISTENTES (sin cambios)
# ============================================================

class Status(str, Enum):
    RESOLVED = "RESOLVED"       # verbo y operando unicos
    AMBIGUOUS = "AMBIGUOUS"     # >1 candidato sobrevivio la validacion
    UNKNOWN = "UNKNOWN"         # no esta en el lexico, o no mapea a primitiva
    INCOMPLETE = "INCOMPLETE"   # verbo si, operando requerido no


@dataclass(frozen=True, slots=True)
class Concept:
    ili: str | None
    lemma: str


@dataclass(frozen=True, slots=True)
class Provenance:
    """Obligatoria en toda IR emitida, incluso en UNKNOWN.

    Si una interpretacion resulta incorrecta, esto es lo que permite saber
    exactamente que capa la produjo.
    """
    surface: str
    language: str
    lexical_source: str
    resolution: str            # "lexicon" | "llm_proposed+lexicon_validated"
    confidence: str            # "exact" | "proposed" | "surface_only"
    mode: str                  # "strict" | "assisted"
    cache_key: str | None = None
    degraded: str | None = None  # razon, si el sistema corrio degradado

    def to_dict(self) -> dict:
        return {
            "surface": self.surface,
            "language": self.language,
            "lexical_source": self.lexical_source,
            "resolution": self.resolution,
            "confidence": self.confidence,
            "mode": self.mode,
            "cache_key": self.cache_key,
            "degraded": self.degraded,
        }


@dataclass(frozen=True, slots=True)
class Intent:
    verb: Concept | None
    operand: Concept | None
    scope: Concept | None
    status: Status
    provenance: Provenance
    primitive: str | None = None
    candidates: tuple[str, ...] = ()

    def can_act(self) -> bool:
        """Unico punto donde se decide si esto puede convertirse en accion."""
        return self.status is Status.RESOLVED

    def key(self) -> tuple:
        """Identidad semantica, sin superficie. Base de la invariante de separacion."""
        return (self.primitive,
                self.operand.ili if self.operand else None,
                self.scope.ili if self.scope else None)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["status"] = self.status.value
        data["schema"] = "intent/1"
        return data
