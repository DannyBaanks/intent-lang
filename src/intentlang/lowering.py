"""Lowering: Intent -> Program IR.

Convierte un Intent RESOLVED en un Program ejecutable.
"""
from __future__ import annotations

from .ir import Intent, Status
from .program import (
    Program,
    ProgramNode,
    call,
    foreach,
    if_,
    let,
    try_,
    value,
)
from .resolve import resolve

# Mapeo primitiva -> capability
PRIMITIVE_TO_CAPABILITY: dict[str, str] = {
    # v1 original
    "COPY": "cap.fs.copy",
    "MOVE": "cap.fs.move",
    "REMOVE": "cap.fs.delete",
    "RUN": "cap.process.run",
    "QUERY": "cap.query.exec",
    "CHANGE": "cap.fs.modify",
    "ADD": "cap.fs.write",
    "CONNECT": "cap.net.connect",
    # Efectos extendidos
    "DOWNLOAD": "cap.net.download",
    "COMPILE": "cap.build.compile",
    "RENDER": "cap.media.render",
    "SIGN": "cap.crypto.sign",
    "WRITE": "cap.fs.write",
    "READ": "cap.fs.read",
    "DELETE": "cap.fs.delete",
    "EXECUTE": "cap.process.run",
    "ARCHIVE": "cap.archive.create",
    "EXTRACT": "cap.archive.extract",
    "ENCRYPT": "cap.crypto.encrypt",
    "DECRYPT": "cap.crypto.decrypt",
}


# Mapeo primitiva -> nombres de parámetros de capability (Coincide con capabilities.py)
PRIMITIVE_TO_CAPABILITY_ARGS: dict[str, list[str]] = {
    "COPY": ["src", "dst"],
    "MOVE": ["src", "dst"],
    "REMOVE": ["path"],
    "RUN": ["cmd"],
    "QUERY": ["query"],
    "CHANGE": ["path", "operation", "content"],
    "ADD": ["path", "content"],          # fs.write
    "CONNECT": ["host", "port"],
    "DOWNLOAD": ["url", "dest"],
    "COMPILE": ["source", "output"],
    "RENDER": ["source", "output", "format"],
    "SIGN": ["data", "private_key"],     # crypto.sign
    "WRITE": ["path", "content"],
    "READ": ["path"],
    "DELETE": ["path"],
    "EXECUTE": ["cmd"],                  # process.run
    "ARCHIVE": ["source", "output"],
    "EXTRACT": ["archive", "dest"],
    "ENCRYPT": ["data", "key"],
    "DECRYPT": ["encrypted", "key", "iv"],  # crypto.decrypt
}


def _build_arg_nodes(intent: Intent) -> list[ProgramNode]:
    """Construye nodos de argumento desde el intent."""
    nodes = []
    if intent.verb:
        nodes.append(value(intent.verb.lemma))
    if intent.operand:
        nodes.append(value(intent.operand.lemma))
    if intent.scope:
        nodes.append(value(intent.scope.lemma))
    return nodes


def _build_kwarg_nodes(intent: Intent) -> dict[str, ProgramNode]:
    """Construye nodos de kwargs mapeados a nombres de parámetros de capability."""
    _capability = PRIMITIVE_TO_CAPABILITY.get(intent.primitive or "", "")
    arg_names = PRIMITIVE_TO_CAPABILITY_ARGS.get(intent.primitive or "", [])
    
    nodes = {}
    args = _build_arg_nodes(intent)
    for i, arg_name in enumerate(arg_names):
        if i < len(args):
            nodes[arg_name] = args[i]
    return nodes


def _build_operand_kwarg_nodes(intent: Intent) -> dict[str, ProgramNode]:
    """Construye kwargs usando operand como source y scope como destination para COPY/MOVE.
    
    Para COPY/MOVE: operand = source, scope = destination
    Para otras primitivas: usa _build_kwarg_nodes normal
    """
    primitive = intent.primitive
    if primitive in ("COPY", "MOVE"):
        # src/dst estan fijados aqui y tambien en PRIMITIVE_TO_CAPABILITY_ARGS["COPY"/"MOVE"].
        # Dos fuentes de verdad para los mismos nombres: si cambia la tabla, cambiar tambien aqui.
        nodes = {}
        # operand = source, scope = destination
        if intent.operand:
            nodes["src"] = value(intent.operand.lemma)
        if intent.scope:
            nodes["dst"] = value(intent.scope.lemma)
        return nodes
    
    # Fallback para otras primitivas
    return _build_kwarg_nodes(intent)


def lower_intent_to_program(intent: Intent) -> Program:
    """Convierte un Intent RESOLVED en Program IR ejecutable.
    
    Para COPY/MOVE: solo kwargs (src, dst) desde operand/scope.
    Para otras primitivas: positional args + kwargs segun PRIMITIVE_TO_CAPABILITY_ARGS.
    """
    if intent.status is not Status.RESOLVED:
        raise ValueError(f"Cannot lower {intent.status} intent: not RESOLVED")
    
    primitive = intent.primitive
    capability = PRIMITIVE_TO_CAPABILITY.get(primitive or "")
    
    if not capability:
        raise ValueError(f"No capability mapping for primitive: {primitive}")
    
    # COPY/MOVE: solo kwargs, sin posicionales
    if primitive in ("COPY", "MOVE"):
        kwarg_nodes = _build_operand_kwarg_nodes(intent)
        root = call(capability, **kwarg_nodes)
    else:
        # Otras primitivas: positional + kwargs
        arg_nodes = _build_arg_nodes(intent)
        kwarg_nodes = _build_kwarg_nodes(intent)
        root = call(capability, *arg_nodes, **kwarg_nodes)
    
    return Program(root=root, provenance=intent.provenance)


def lower_text_to_program(text: str, lang: str, mode: str = "strict") -> Program:
    """Pipeline completo: texto -> intent -> program."""
    intent = resolve(text, lang, mode=mode)
    return lower_intent_to_program(intent)


def lower_with_bindings(text: str, lang: str, bindings: dict[str, ProgramNode], 
                        mode: str = "strict") -> Program:
    """Lower con bindings previos (para programas complejos)."""
    intent = resolve(text, lang, mode=mode)
    prog = lower_intent_to_program(intent)
    
    if bindings:
        # Envolver root con bindings
        new_root = let(bindings, prog.root)
        prog = Program(root=new_root, globals={**prog.globals, **bindings}, provenance=prog.provenance)
    
    return prog


# ============================================================
# Lowering avanzado: patrones compuestos
# ============================================================

def lower_batch_copy(text: str, lang: str, items_var: str, dest_var: str, 
                     mode: str = "strict") -> Program:
    """LOWER para 'copia todos los X a Y' -> FOREACH + CALL copy."""
    intent = resolve(text, lang, mode=mode)
    if intent.status is not Status.RESOLVED:
        raise ValueError(f"Intent not resolved: {intent.status}")
    
    # items_var y dest_var son nombres de variables que se bindean externamente
    item = value(items_var)
    dest = value(dest_var)
    
    body = call("cap.fs.copy", item, dest)
    loop_node = foreach(item, body)
    
    return Program(root=loop_node, provenance=intent.provenance)


def lower_conditional_copy(text: str, lang: str, condition: ProgramNode,
                           true_branch: ProgramNode, false_branch: ProgramNode,
                           mode: str = "strict") -> Program:
    """LOWER con condicional."""
    intent = resolve(text, lang, mode=mode)
    if_node = if_(condition, true_branch, false_branch)
    return Program(root=if_node, provenance=intent.provenance)


def lower_try_copy(text: str, lang: str, try_body: ProgramNode,
                   catch_body: ProgramNode | None = None,
                   mode: str = "strict") -> Program:
    """LOWER con try/catch."""
    intent = resolve(text, lang, mode=mode)
    try_node = try_(try_body, catch_body)
    return Program(root=try_node, provenance=intent.provenance)
