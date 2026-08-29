"""Program IR: arbol de composicion de primitivas.

Un Program es un arbol de ProgramNode que representa una computacion
completa: efectos, transformacion de datos y control de flujo.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .ir import Provenance


@dataclass(frozen=True, slots=True)
class ProgramNode:
    """Nodo en el arbol de programa. Composicion de primitivas."""
    primitive: str
    args: tuple[ProgramNode, ...] = ()
    kwargs: dict[str, Any] = field(default_factory=dict)
    binds: dict[str, ProgramNode] = field(default_factory=dict)  # for LET/BIND

    def __post_init__(self):
        # Validar que primitive existe
        from .ir import PRIMITIVES
        if self.primitive not in PRIMITIVES:
            raise ValueError(f"Primitive desconocida: {self.primitive}")

    def to_dict(self) -> dict:
        def _to_dict(v):
            if isinstance(v, ProgramNode):
                return v.to_dict()
            return v
        return {
            "primitive": self.primitive,
            "args": [_to_dict(a) for a in self.args],
            "kwargs": {k: _to_dict(v) for k, v in self.kwargs.items()},
            "binds": {k: _to_dict(v) for k, v in self.binds.items()},
        }


@dataclass(frozen=True, slots=True)
class Program:
    """Programa completo: raiz + bindings globales + metadatos."""
    root: ProgramNode
    globals: dict[str, ProgramNode] = field(default_factory=dict)
    provenance: Provenance | None = None

    def to_dict(self) -> dict:
        return {
            "root": self.root.to_dict(),
            "globals": {k: v.to_dict() for k, v in self.globals.items()},
            "provenance": self.provenance.to_dict() if self.provenance else None,
            "schema": "program/1",
        }

    def __str__(self) -> str:
        return self._pretty(self.root, 0)

    def _pretty(self, node: ProgramNode, indent: int) -> str:
        pad = "  " * indent
        args_str = ", ".join(self._pretty(a, indent + 1) for a in node.args)
        kwargs_str = ", ".join(f"{k}={self._pretty(v, indent + 1)}" for k, v in node.kwargs.items())
        parts = []
        if args_str:
            parts.append(args_str)
        if kwargs_str:
            parts.append(kwargs_str)
        inner = ", ".join(parts)
        return f"{pad}{node.primitive}({inner})"


# ============================================================
# Builders ergonomicos
# ============================================================

def value(val: Any) -> ProgramNode:
    """Literal value node."""
    return ProgramNode("VALUE", kwargs={"raw": val})


def ref(name: str) -> ProgramNode:
    """Reference a value established by a binding."""
    return ProgramNode("REFERENCE", kwargs={"name": name})


def seq(*nodes: ProgramNode) -> ProgramNode:
    """Secuencia: A; B; C"""
    return ProgramNode("SEQUENCE", args=nodes)


def if_(cond: ProgramNode, then_: ProgramNode, else_: ProgramNode | None = None) -> ProgramNode:
    """Condicional: IF cond THEN then_ ELSE else_"""
    kwargs = {"then": then_}
    if else_ is not None:
        kwargs["else"] = else_
    return ProgramNode("IF", args=(cond,), kwargs=kwargs)


def loop(iterable: ProgramNode, body: ProgramNode) -> ProgramNode:
    """Loop: for-each iterable do body"""
    return ProgramNode("LOOP", args=(iterable, body))


def foreach(iterable: ProgramNode, body: ProgramNode) -> ProgramNode:
    """Explicit for-each."""
    return ProgramNode("FOREACH", args=(iterable, body))


def call(capability: str, *args: ProgramNode, **kwargs: Any) -> ProgramNode:
    """Llamada a capability: CALL(capability, arg1, arg2, ...)."""
    cap_node = ProgramNode("VALUE", kwargs={"raw": capability})
    return ProgramNode("CALL", args=(cap_node, *args), kwargs=kwargs)


def bind(name: str, value_node: ProgramNode) -> ProgramNode:
    """Binding: LET name = value_node"""
    return ProgramNode("BIND", kwargs={
        "name": value(name),
        "value": value_node,
    })


def let(bindings: dict[str, ProgramNode], body: ProgramNode) -> ProgramNode:
    """LET bindings IN body (como where en Haskell)."""
    bind_nodes = [bind(k, v) for k, v in bindings.items()]
    return ProgramNode("SEQUENCE", args=(*tuple(bind_nodes), body))


def map_(func: ProgramNode, iterable: ProgramNode) -> ProgramNode:
    """MAP: transform each element."""
    return ProgramNode("MAP", args=(func, iterable))


def filter_(predicate: ProgramNode, iterable: ProgramNode) -> ProgramNode:
    """FILTER: keep if predicate."""
    return ProgramNode("FILTER", args=(predicate, iterable))


def collect(iterable: ProgramNode, reducer: ProgramNode | None = None) -> ProgramNode:
    """COLLECT/REDUCE: aggregate."""
    args: tuple[ProgramNode, ...] = (iterable,)
    if reducer:
        args = (iterable, reducer)
    return ProgramNode("COLLECT", args=args)


def compare(op: str, left: ProgramNode, right: ProgramNode) -> ProgramNode:
    """COMPARE: eq, lt, gt, contains, etc."""
    return ProgramNode("COMPARE", args=(left, right), kwargs={"op": value(op)})


def load(source: ProgramNode) -> ProgramNode:
    """LOAD: read from source."""
    return ProgramNode("LOAD", args=(source,))


def store(target: ProgramNode, value_node: ProgramNode) -> ProgramNode:
    """STORE: write to target."""
    return ProgramNode("STORE", args=(target, value_node))


def try_(try_body: ProgramNode, catch_body: ProgramNode | None = None, 
         finally_body: ProgramNode | None = None) -> ProgramNode:
    """TRY/CATCH/FINALLY."""
    kwargs = {"try": try_body}
    if catch_body:
        kwargs["catch"] = catch_body
    if finally_body:
        kwargs["finally"] = finally_body
    return ProgramNode("TRY", args=(), kwargs=kwargs)


def transaction(paths: ProgramNode, body: ProgramNode) -> ProgramNode:
    """Execute a body while protecting explicitly listed filesystem paths."""
    return ProgramNode("TRANSACTION", args=(body,), kwargs={"paths": paths})
