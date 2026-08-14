"""Autoridad de intencion: que intenciones existen.

El lexico dice que significa una palabra. Esta tabla dice cuales de esos
significados son intenciones que el sistema reconoce. Son autoridades
distintas, y la mayoria de los AMBIGUOUS/UNKNOWN salen de esta.
"""
from __future__ import annotations

import functools
import json
from pathlib import Path

from .ir import PRIMITIVES

MAX_ENTRIES = 50
_DEFAULT = Path(__file__).resolve().parents[2] / "data" / "concept_map.json"

#: Cobertura que sabemos que falta, por concepto. Medido en el spike de la
#: Tarea 2, no supuesto. `test_cada_concepto_existe_en_los_tres_idiomas`
#: compara la realidad contra esta declaracion y falla si divergen: agregar un
#: hueco tiene que ser un acto deliberado.
DECLARED_GAPS: dict[str, list[str]] = {
    "i22623": ["zh"],   # ADD: omw-cmn:1.4 no tiene este sentido
}


class InvalidConceptMap(Exception):
    """La tabla esta mal formada. Error duro al arrancar, no degradacion."""


@functools.lru_cache(maxsize=4)
def load_map(path: Path | None = None) -> dict[str, str]:
    raw = json.loads((path or _DEFAULT).read_text(encoding="utf-8"))
    mapping = {k: v for k, v in raw.items() if not k.startswith("_")}

    invalidas = {k: v for k, v in mapping.items() if v not in PRIMITIVES}
    if invalidas:
        raise InvalidConceptMap(f"apuntan a primitivas inexistentes: {invalidas}")
    if len(mapping) > MAX_ENTRIES:
        raise InvalidConceptMap(
            f"{len(mapping)} entradas supera el techo de {MAX_ENTRIES}: "
            "falta un dominio, no mas primitivas")
    return mapping


def primitive_for(ili: str) -> str | None:
    """Primitiva del concepto, o None. Nunca adivina."""
    return load_map().get(ili)
