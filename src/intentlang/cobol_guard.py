"""Fail-closed inverse verification for the generated COBOL subset.

This is intentionally not a general COBOL parser.  It recognizes the small,
structured dialect emitted by :mod:`portable_codegen` and recovers capability
calls from it.  Unknown COBOL is rejected rather than treated as equivalent.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .capabilities import validate_inputs
from .program import Program, ProgramNode


@dataclass(frozen=True, slots=True)
class CobolVerification:
    passed: bool
    reason: str
    expected: tuple[dict[str, Any], ...] = ()
    recovered: tuple[dict[str, Any], ...] = ()


_SELECT_RE = re.compile(r"^SELECT\s+(\S+)\s+ASSIGN TO\s+(.+)$", re.IGNORECASE)
_OPEN_RE = re.compile(r"^OPEN\s+(OUTPUT|INPUT)\s+(\S+)$", re.IGNORECASE)
_MOVE_RE = re.compile(r"^MOVE\s+(.+)\s+TO\s+(\S+)$", re.IGNORECASE)
_WRITE_RE = re.compile(r"^WRITE\s+(\S+)$", re.IGNORECASE)
_READ_RE = re.compile(r"^READ\s+(\S+)\s+INTO\s+(\S+)$", re.IGNORECASE)
_CALL_RE = re.compile(
    r"^CALL\s+'([^']+)'\s+USING\s+(.+?)\s+RETURNING\s+\S+$",
    re.IGNORECASE,
)


def verify_cobol_round_trip(program: Program, source: str) -> CobolVerification:
    """Recover and compare a linear Program IR from generated COBOL.

    The verifier validates the recovered input objects against the registered
    capability schemas before comparing them.  It does not execute COBOL.
    Compilation and execution remain separate gates.
    """
    try:
        expected = _linear_expected(program)
    except ValueError as exc:
        return CobolVerification(False, f"NOT_SUPPORTED: {exc}")

    recovered, error = _recover(source)
    if error:
        return CobolVerification(False, error, expected=expected)

    defense_error = _check_defenses(expected, source)
    if defense_error:
        return CobolVerification(False, defense_error, expected=expected, recovered=recovered)

    if expected != recovered:
        return CobolVerification(
            False,
            "MISMATCH: recovered capability sequence differs from Program IR",
            expected=expected,
            recovered=recovered,
        )
    return CobolVerification(True, "PASS", expected=expected, recovered=recovered)


def _linear_expected(program: Program) -> tuple[dict[str, Any], ...]:
    nodes = _flatten_sequence(program.root)
    expected: list[dict[str, Any]] = []
    for node in nodes:
        if node.primitive != "CALL" or not node.args:
            raise ValueError(f"only linear CALL programs are supported ({node.primitive})")
        cap_node = node.args[0]
        capability = cap_node.kwargs.get("raw") if cap_node.primitive == "VALUE" else None
        if not isinstance(capability, str):
            raise ValueError("CALL capability must be a literal")
        inputs: dict[str, Any] = {}
        for name, value_node in node.kwargs.items():
            if not isinstance(value_node, ProgramNode) or value_node.primitive != "VALUE":
                raise ValueError(f"{capability} uses a non-literal input")
            inputs[name] = value_node.kwargs.get("raw")
        if not validate_inputs(capability, inputs):
            raise ValueError(f"input contract rejected {capability}")
        expected.append({"capability": capability, "inputs": inputs})
    return tuple(expected)


def _flatten_sequence(node: ProgramNode) -> tuple[ProgramNode, ...]:
    if node.primitive == "SEQUENCE":
        result: list[ProgramNode] = []
        for child in node.args:
            result.extend(_flatten_sequence(child))
        return tuple(result)
    return (node,)


def _recover(source: str) -> tuple[tuple[dict[str, Any], ...], str | None]:
    if "TODO(cobol-backend)" in source:
        return (), "NOT_SUPPORTED: source contains an unimplemented COBOL hook"
    if "IDENTIFICATION DIVISION." not in source or "PROCEDURE DIVISION." not in source:
        return (), "NOT_SUPPORTED: not a generated COBOL program"

    files: dict[str, str] = {}
    records: set[str] = set()
    for raw_line in source.splitlines():
        line = raw_line.strip()
        match = _SELECT_RE.match(line)
        if match:
            path = _parse_literal(match.group(2))
            if not isinstance(path, str):
                return (), "NOT_SUPPORTED: dynamic COBOL file assignment"
            files[match.group(1).upper()] = path
        elif line.startswith("01 ") and " PIC X(4096)." in line:
            records.add(line[3:].split(" PIC", 1)[0].strip().upper())

    recovered: list[dict[str, Any]] = []
    pending_open: tuple[str, str] | None = None
    pending_write: tuple[str, str] | None = None
    for raw_line in source.splitlines():
        line = raw_line.strip()
        if line.startswith("DISPLAY ") and not (
            any(line == f"DISPLAY {record}" for record in records)
            or line.startswith("DISPLAY 'CRITICAL:")
        ):
            return (), "NOT_SUPPORTED: unexpected COBOL DISPLAY statement"
        match = _OPEN_RE.match(line)
        if match:
            pending_open = (match.group(1).upper(), match.group(2).upper())
            continue
        match = _MOVE_RE.match(line)
        if match and match.group(2).upper() in records and pending_open:
            raw_value = _parse_literal(match.group(1))
            if not isinstance(raw_value, str) or pending_open[0] != "OUTPUT":
                return (), "NOT_SUPPORTED: dynamic or malformed COBOL write"
            pending_write = (pending_open[1], raw_value)
            continue
        match = _WRITE_RE.match(line)
        if match and pending_write and match.group(1).upper() in records:
            file_name, content = pending_write
            if file_name not in files:
                return (), "MISMATCH: WRITE has no matching SELECT"
            recovered.append({"capability": "cap.fs.write", "inputs": {"path": files[file_name], "content": content}})
            pending_write = None
            continue
        match = _READ_RE.match(line)
        if match and pending_open and pending_open[0] == "INPUT":
            if match.group(2).upper() not in records or pending_open[1] not in files:
                return (), "MISMATCH: READ has no matching SELECT or record"
            recovered.append({"capability": "cap.fs.read", "inputs": {"path": files[pending_open[1]]}})
            continue
        match = _CALL_RE.match(line)
        if match:
            capability_by_routine = {
                "CBL-COPY-FILE": "cap.fs.copy",
                "CBL-RENAME-FILE": "cap.fs.move",
                "CBL-DELETE-FILE": "cap.fs.delete",
                "SYSTEM": "cap.process.run",
            }
            capability = capability_by_routine.get(match.group(1).upper())
            if capability is None:
                return (), f"NOT_SUPPORTED: unknown COBOL routine {match.group(1)!r}"
            arguments = _split_literals(match.group(2))
            first = arguments[0] if arguments else None
            second = arguments[1] if len(arguments) > 1 else None
            if capability == "cap.process.run":
                inputs = {"cmd": first}
            elif capability == "cap.fs.delete":
                inputs = {"path": first}
            else:
                inputs = {"src": first, "dst": second}
            if not all(isinstance(value, str) for value in inputs.values()):
                return (), "NOT_SUPPORTED: dynamic COBOL CALL inputs"
            recovered.append({"capability": capability, "inputs": inputs})

    if pending_write:
        return (), "MISMATCH: incomplete COBOL write"
    return tuple(recovered), None


def _check_defenses(expected: tuple[dict[str, Any], ...], source: str) -> str | None:
    if not any(item["capability"] in {"cap.fs.write", "cap.fs.read"} for item in expected):
        return None
    required = (
        "WS-MAX-RECORD-SIZE",
        "MOVE 99 TO RETURN-CODE",
        "STOP RUN",
        "FILE STATUS IS WS-FILE-STATUS.",
        "CRITICAL: FILE STATUS VIOLATION",
    )
    missing = [fragment for fragment in required if fragment not in source]
    if missing:
        return f"INVARIANT_VIOLATION: missing COBOL defense {missing[0]!r}"
    for item in expected:
        if item["capability"] not in {"cap.fs.write", "cap.fs.read"}:
            continue
        label = "WRITE record" if item["capability"] == "cap.fs.write" else "READ record"
        if f"{label} OUT OF BOUNDS" not in source:
            return f"INVARIANT_VIOLATION: missing size defense for {label}"
        if item["capability"] == "cap.fs.write":
            content = item["inputs"].get("content")
            literal = "'" + content.replace("'", "''") + "'" if isinstance(content, str) else None
            condition = re.escape(f"IF FUNCTION LENGTH({literal}) > WS-MAX-RECORD-SIZE")
        else:
            if "WS-INPUT-SIZE" not in source or "RECORD IS VARYING IN SIZE" not in source:
                return "INVARIANT_VIOLATION: READ has no measured variable-length record"
            condition = r"IF WS-INPUT-SIZE > WS-MAX-RECORD-SIZE"
        if not re.search(condition, source):
            return f"INVARIANT_VIOLATION: missing size condition for {label}"
    return None


def _parse_literal(raw: str) -> str | None:
    value = raw.strip()
    if len(value) < 2 or not (value.startswith("'") and value.endswith("'")):
        return None
    return value[1:-1].replace("''", "'")


def _split_literals(raw: str) -> list[str | None]:
    """Split the generated USING clause without accepting arbitrary COBOL."""
    values: list[str | None] = []
    token = ""
    in_literal = False
    index = 0
    while index < len(raw):
        char = raw[index]
        if char == "'":
            token += char
            if in_literal and index + 1 < len(raw) and raw[index + 1] == "'":
                token += "'"
                index += 1
            else:
                in_literal = not in_literal
        elif char.isspace() and not in_literal:
            if token:
                values.append(_parse_literal(token))
                token = ""
        else:
            token += char
        index += 1
    if token:
        values.append(_parse_literal(token))
    return values
