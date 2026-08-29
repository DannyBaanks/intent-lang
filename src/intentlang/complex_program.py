"""Structured programs: parse, type-check, plan and execute safely."""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .capabilities import CAPABILITY_REGISTRY
from .executor import execute_program
from .program import Program, ProgramNode, bind, call, compare, ref, seq, transaction, try_, value


class ValueType(str, Enum):
    BOOL = "Bool"
    NUMBER = "Number"
    TEXT = "Text"
    LIST = "List"
    OBJECT = "Object"
    NULL = "Null"
    UNKNOWN = "Unknown"


class Effect(str, Enum):
    FILESYSTEM_READ = "filesystem.read"
    FILESYSTEM_WRITE = "filesystem.write"
    NETWORK = "network"
    PROCESS = "process"
    CRYPTO = "crypto"
    MEDIA = "media"
    ARCHIVE = "archive"
    BUILD = "build"


@dataclass(frozen=True, slots=True)
class TypeIssue:
    path: str
    message: str


@dataclass(frozen=True, slots=True)
class ProgramPlan:
    effects: tuple[str, ...]
    capabilities: tuple[str, ...]
    requires_confirmation: bool

    def to_dict(self) -> dict[str, Any]:
        return {"effects": list(self.effects), "capabilities": list(self.capabilities), "requires_confirmation": self.requires_confirmation}


class ProgramTypeError(ValueError):
    """Raised when a structured program is not type-safe."""


class PermissionError(ValueError):
    """Raised when a program requests an effect outside its policy."""


_CAPABILITY_EFFECTS: dict[str, str] = {
    "cap.fs.read": Effect.FILESYSTEM_READ,
    "cap.fs.copy": Effect.FILESYSTEM_WRITE,
    "cap.fs.move": Effect.FILESYSTEM_WRITE,
    "cap.fs.delete": Effect.FILESYSTEM_WRITE,
    "cap.fs.write": Effect.FILESYSTEM_WRITE,
    "cap.fs.modify": Effect.FILESYSTEM_WRITE,
    "cap.process.run": Effect.PROCESS,
    "cap.net.connect": Effect.NETWORK,
    "cap.net.download": Effect.NETWORK,
    "cap.crypto.hash": Effect.CRYPTO,
    "cap.crypto.encrypt": Effect.CRYPTO,
    "cap.crypto.decrypt": Effect.CRYPTO,
    "cap.crypto.sign": Effect.CRYPTO,
    "cap.crypto.verify": Effect.CRYPTO,
    "cap.media.render": Effect.MEDIA,
    "cap.media.convert": Effect.MEDIA,
    "cap.archive.create": Effect.ARCHIVE,
    "cap.archive.extract": Effect.ARCHIVE,
    "cap.build.compile": Effect.BUILD,
    "cap.build.test": Effect.BUILD,
}


def _literal_type(raw: Any) -> ValueType:
    if isinstance(raw, bool):
        return ValueType.BOOL
    if isinstance(raw, (int, float)):
        return ValueType.NUMBER
    if isinstance(raw, str):
        return ValueType.TEXT
    if isinstance(raw, list):
        return ValueType.LIST
    if isinstance(raw, dict):
        return ValueType.OBJECT
    if raw is None:
        return ValueType.NULL
    return ValueType.UNKNOWN


def _schema_type(schema: dict[str, Any]) -> ValueType:
    schema_name = schema.get("type")
    if not isinstance(schema_name, str):
        return ValueType.UNKNOWN
    return {
        "boolean": ValueType.BOOL,
        "integer": ValueType.NUMBER,
        "number": ValueType.NUMBER,
        "string": ValueType.TEXT,
        "array": ValueType.LIST,
        "object": ValueType.OBJECT,
    }.get(schema_name, ValueType.UNKNOWN)


def _walk(node: ProgramNode, path: str, env: dict[str, ValueType], issues: list[TypeIssue], effects: set[str], caps: set[str]) -> ValueType:
    if node.primitive == "VALUE":
        return _literal_type(node.kwargs.get("raw"))
    if node.primitive == "REFERENCE":
        name = node.kwargs.get("name")
        if not isinstance(name, str) or name not in env:
            issues.append(TypeIssue(path, f"unknown reference: {name!r}"))
            return ValueType.UNKNOWN
        return env[name]
    if node.primitive == "BIND":
        name_node = node.kwargs.get("name")
        value_node = node.kwargs.get("value")
        name = name_node.kwargs.get("raw") if isinstance(name_node, ProgramNode) else None
        if not isinstance(name, str) or not isinstance(value_node, ProgramNode):
            issues.append(TypeIssue(path, "BIND requires a text name and value"))
            return ValueType.UNKNOWN
        env[name] = _walk(value_node, f"{path}.value", env, issues, effects, caps)
        return env[name]
    if node.primitive == "SEQUENCE":
        result = ValueType.NULL
        for index, child in enumerate(node.args):
            result = _walk(child, f"{path}.args[{index}]", env, issues, effects, caps)
        return result
    if node.primitive == "IF":
        condition = node.args[0] if node.args else None
        if isinstance(condition, ProgramNode):
            condition_type = _walk(condition, f"{path}.condition", env, issues, effects, caps)
            if condition_type not in (ValueType.BOOL, ValueType.UNKNOWN):
                issues.append(TypeIssue(path, "IF condition must be Bool"))
        for branch in (node.kwargs.get("then"), node.kwargs.get("else")):
            if isinstance(branch, ProgramNode):
                _walk(branch, f"{path}.branch", env.copy(), issues, effects, caps)
        return ValueType.UNKNOWN
    if node.primitive == "FOREACH":
        iterable = node.args[0] if node.args else None
        if isinstance(iterable, ProgramNode):
            iterable_type = _walk(iterable, f"{path}.iterable", env, issues, effects, caps)
            if iterable_type not in (ValueType.LIST, ValueType.UNKNOWN):
                issues.append(TypeIssue(path, "FOREACH iterable must be List"))
        variable = node.kwargs.get("var")
        if isinstance(variable, ProgramNode):
            name = variable.kwargs.get("raw")
            if isinstance(name, str):
                body_env = env.copy()
                body_env[name] = ValueType.UNKNOWN
                body = node.args[1] if len(node.args) > 1 else None
                if isinstance(body, ProgramNode):
                    _walk(body, f"{path}.body", body_env, issues, effects, caps)
        return ValueType.UNKNOWN
    if node.primitive == "COMPARE":
        for index, child in enumerate(node.args):
            _walk(child, f"{path}.args[{index}]", env, issues, effects, caps)
        return ValueType.BOOL
    if node.primitive == "RETURN":
        if node.args:
            _walk(node.args[0], f"{path}.value", env, issues, effects, caps)
        return ValueType.UNKNOWN
    if node.primitive == "TRY":
        body = node.kwargs.get("try")
        if isinstance(body, ProgramNode):
            _walk(body, f"{path}.try", env.copy(), issues, effects, caps)
        for key in ("catch", "finally"):
            branch = node.kwargs.get(key)
            if isinstance(branch, ProgramNode):
                _walk(branch, f"{path}.{key}", env.copy(), issues, effects, caps)
        return ValueType.UNKNOWN
    if node.primitive == "TRANSACTION":
        paths = node.kwargs.get("paths")
        if isinstance(paths, ProgramNode):
            if _walk(paths, f"{path}.paths", env, issues, effects, caps) not in (ValueType.LIST, ValueType.UNKNOWN):
                issues.append(TypeIssue(path, "TRANSACTION paths must be List"))
        if node.args and isinstance(node.args[0], ProgramNode):
            _walk(node.args[0], f"{path}.body", env.copy(), issues, effects, caps)
        return ValueType.UNKNOWN
    if node.primitive == "CALL":
        cap_node = node.args[0] if node.args else None
        capability = cap_node.kwargs.get("raw") if isinstance(cap_node, ProgramNode) else None
        if not isinstance(capability, str) or capability not in CAPABILITY_REGISTRY:
            issues.append(TypeIssue(path, f"unknown capability: {capability!r}"))
            return ValueType.UNKNOWN
        caps.add(capability)
        effects.add(_CAPABILITY_EFFECTS.get(capability, "unknown"))
        contract = CAPABILITY_REGISTRY[capability]
        required = contract.input_schema.get("required", [])
        missing = [key for key in required if key not in node.kwargs]
        if missing:
            issues.append(TypeIssue(path, f"missing required inputs: {', '.join(missing)}"))
        properties = contract.input_schema.get("properties", {})
        for key, child in node.kwargs.items():
            if isinstance(child, ProgramNode):
                child_type = _walk(child, f"{path}.{key}", env, issues, effects, caps)
                expected = _schema_type(properties.get(key, {}))
                if expected is not ValueType.UNKNOWN and child_type not in (expected, ValueType.UNKNOWN):
                    issues.append(TypeIssue(f"{path}.{key}", f"expected {expected.value}, got {child_type.value}"))
        return ValueType.OBJECT
    for index, child in enumerate(node.args):
        _walk(child, f"{path}.args[{index}]", env, issues, effects, caps)
    return ValueType.UNKNOWN


def check_program(program: Program) -> list[TypeIssue]:
    issues: list[TypeIssue] = []
    _walk(program.root, "root", {}, issues, set(), set())
    return issues


def plan_program(program: Program, *, allowed_effects: set[str] | None = None) -> ProgramPlan:
    issues = check_program(program)
    if issues:
        raise ProgramTypeError("; ".join(f"{i.path}: {i.message}" for i in issues))
    effects: set[str] = set()
    capabilities: set[str] = set()
    _walk(program.root, "root", {}, [], effects, capabilities)
    if allowed_effects is not None:
        denied = effects - allowed_effects
        if denied:
            raise PermissionError(f"effects not allowed: {', '.join(sorted(denied))}")
    return ProgramPlan(tuple(sorted(effects)), tuple(sorted(capabilities)), bool(effects - {Effect.FILESYSTEM_READ}))


def _node_from_json(item: Any) -> ProgramNode:
    if isinstance(item, dict) and set(item) == {"$ref"}:
        return ref(item["$ref"])
    if isinstance(item, dict) and "call" in item:
        return call(item["call"], **{key: _node_from_json(val) for key, val in item.get("inputs", {}).items()})
    if isinstance(item, dict) and "sequence" in item:
        return seq(*(_node_from_json(child) for child in item["sequence"]))
    if isinstance(item, dict) and "let" in item:
        binding = item["let"]
        return seq(bind(binding["name"], _node_from_json(binding["value"])), _node_from_json(binding["in"]))
    if isinstance(item, dict) and "if" in item:
        branch = item["if"]
        kwargs = {"then": _node_from_json(branch["then"])}
        if "else" in branch:
            kwargs["else"] = _node_from_json(branch["else"])
        return ProgramNode("IF", args=(_node_from_json(branch["condition"]),), kwargs=kwargs)
    if isinstance(item, dict) and "foreach" in item:
        loop = item["foreach"]
        return ProgramNode(
            "FOREACH",
            args=(_node_from_json(loop["in"]), _node_from_json(loop["do"])),
            kwargs={"var": value(loop["as"])},
        )
    if isinstance(item, dict) and "compare" in item:
        comparison = item["compare"]
        return compare(comparison["op"], _node_from_json(comparison["left"]), _node_from_json(comparison["right"]))
    if isinstance(item, dict) and "return" in item:
        return ProgramNode("RETURN", args=(_node_from_json(item["return"]),))
    if isinstance(item, dict) and "try" in item:
        block = item["try"]
        return try_(
            _node_from_json(block["body"]),
            _node_from_json(block["catch"]) if "catch" in block else None,
            _node_from_json(block["finally"]) if "finally" in block else None,
        )
    if isinstance(item, dict) and "transaction" in item:
        block = item["transaction"]
        return transaction(_node_from_json(block["paths"]), _node_from_json(block["body"]))
    return value(item)


def _substitute_function(item: Any, bindings: dict[str, Any]) -> Any:
    if isinstance(item, dict) and set(item) == {"$ref"} and item["$ref"] in bindings:
        return bindings[item["$ref"]]
    if isinstance(item, dict):
        return {key: _substitute_function(val, bindings) for key, val in item.items()}
    if isinstance(item, list):
        return [_substitute_function(val, bindings) for val in item]
    return item


def _expand_steps(steps: list[Any], functions: dict[str, Any], stack: tuple[str, ...] = ()) -> list[Any]:
    expanded: list[Any] = []
    for step in steps:
        if isinstance(step, dict) and "call_function" in step:
            name = step["call_function"]
            if not isinstance(name, str) or name not in functions:
                raise ValueError(f"unknown function: {name!r}")
            if name in stack:
                raise ValueError(f"recursive function expansion: {' -> '.join((*stack, name))}")
            definition = functions[name]
            if not isinstance(definition, dict) or not isinstance(definition.get("body"), list):
                raise ValueError(f"function {name!r} requires a body array")
            params = definition.get("params", [])
            args = step.get("args", [])
            if not isinstance(params, list) or len(params) != len(args):
                raise ValueError(f"function {name!r} argument count mismatch")
            bindings = dict(zip(params, args, strict=True))
            body = [_substitute_function(item, bindings) for item in definition["body"]]
            expanded.extend(_expand_steps(body, functions, (*stack, name)))
        else:
            expanded.append(step)
    return expanded


def parse_structured(source: str) -> Program:
    """Parse JSON: {\"steps\": [{\"call\": ..., \"inputs\": ...}]} into Program IR."""
    document = json.loads(source)
    if not isinstance(document, dict) or not isinstance(document.get("steps"), list):
        raise ValueError("program must be an object with a 'steps' array")
    functions = document.get("functions", {})
    if not isinstance(functions, dict):
        raise ValueError("program functions must be an object")
    steps = _expand_steps(document["steps"], functions)
    return Program(root=seq(*(_node_from_json(step) for step in steps)))


def run_structured(source: str, *, allowed_effects: set[str] | None = None, confirmed: bool = False) -> tuple[ProgramPlan, dict]:
    program = parse_structured(source)
    plan = plan_program(program, allowed_effects=allowed_effects)
    if plan.requires_confirmation and not confirmed:
        raise PermissionError("confirmation required for side effects")
    return plan, execute_program(program)
