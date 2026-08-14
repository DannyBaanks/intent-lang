"""Representacion canonica de intencion: sin idioma, con procedencia completa."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum

PRIMITIVES: tuple[str, ...] = (
    "ADD", "REMOVE", "MOVE", "CHANGE", "QUERY", "RUN", "COPY", "CONNECT",
)


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
