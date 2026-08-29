"""Executor: recorre ProgramNode y ejecuta capabilities reales.

Maneja:
- Environment (bindings LET/BIND)
- Control flow: SEQUENCE, IF, LOOP, FOREACH, CALL, RETURN
- Exception handling: TRY/CATCH/FINALLY
- Evidence capture per node (stdout, stderr, result, SHA256)
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .capabilities import execute_capability
from .program import Program, ProgramNode

UTC = timezone.utc  # noqa: UP017 - supports the repository's mypy typeshed


@dataclass(frozen=True, slots=True)
class NodeEvidence:
    """Evidencia de ejecución de un nodo."""
    node_primitive: str
    node_id: str
    inputs: dict
    result: dict | None = None
    stdout: str = ""
    stderr: str = ""
    error: str | None = None
    started_at: str = ""
    finished_at: str = ""
    duration_ms: int = 0
    sha256: str = ""

    def to_dict(self) -> dict:
        return {
            "primitive": self.node_primitive,
            "node_id": self.node_id,
            "inputs": self.inputs,
            "result": self.result,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "sha256": self.sha256,
        }


class ExecutionError(Exception):
    """Error durante ejecución con evidencia."""
    def __init__(self, message: str, evidence: NodeEvidence | None = None):
        super().__init__(message)
        self.evidence = evidence


class ReturnSignal(Exception):
    """Señal para RETURN dentro de funciones/bloques."""
    def __init__(self, value: Any):
        self.value = value


class Executor:
    """Ejecuta un Program recursivamente con environment."""

    def __init__(self, capture_output: bool = True):
        self.env: dict[str, Any] = {}  # bindings LET/BIND
        self.evidence_log: list[NodeEvidence] = []
        self.capture_output = capture_output
        self._node_counter = 0

    def _gen_node_id(self) -> str:
        self._node_counter += 1
        return f"n{self._node_counter}"

    def _sha256(self, data: Any) -> str:
        """SHA256 determinista de cualquier objeto serializable."""
        serialized = json.dumps(data, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _capture_streams(self, func: Callable, *args, **kwargs) -> tuple[Any, str, str]:
        """Ejecuta func capturando stdout/stderr."""
        if not self.capture_output:
            return func(*args, **kwargs), "", ""

        old_stdout, old_stderr = sys.stdout, sys.stderr
        from io import StringIO
        sys.stdout, sys.stderr = StringIO(), StringIO()
        try:
            result = func(*args, **kwargs)
            return result, sys.stdout.getvalue(), sys.stderr.getvalue()
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr

    def execute(self, program: Program) -> dict:
        """Ejecuta programa completo. Devuelve resultado + evidence log."""
        self.env = {name: self._execute_node(node) for name, node in program.globals.items()}
        started = datetime.now(UTC).isoformat()
        
        try:
            result = self._execute_node(program.root)
            finished = datetime.now(UTC).isoformat()
            return {
                "status": "OK",
                "result": result,
                "evidence": [e.to_dict() for e in self.evidence_log],
                "started_at": started,
                "finished_at": finished,
            }
        except ReturnSignal as signal:
            finished = datetime.now(UTC).isoformat()
            return {
                "status": "OK",
                "result": signal.value,
                "evidence": [e.to_dict() for e in self.evidence_log],
                "started_at": started,
                "finished_at": finished,
            }
        except Exception as e:
            finished = datetime.now(UTC).isoformat()
            return {
                "status": "ERROR",
                "error": str(e),
                "evidence": [e.to_dict() for e in self.evidence_log],
                "started_at": started,
                "finished_at": finished,
            }

    def _execute_node(self, node: ProgramNode) -> Any:
        """Dispatch por primitiva."""
        method_name = f"_exec_{node.primitive.lower()}"
        method = getattr(self, method_name, None)
        if not method:
            raise ExecutionError(f"No executor for primitive: {node.primitive}")
        return method(node)

    def _record_evidence(self, node: ProgramNode, inputs: dict, 
                         result: Any = None, error: str | None = None,
                         stdout: str = "", stderr: str = "",
                         started_at: str = "", finished_at: str = "",
                         duration_ms: int = 0) -> NodeEvidence:
        """Registra evidencia del nodo."""
        ev = NodeEvidence(
            node_primitive=node.primitive,
            node_id=self._gen_node_id(),
            inputs=inputs,
            result=result,
            stdout=stdout,
            stderr=stderr,
            error=error,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            sha256=self._sha256({
                "primitive": node.primitive,
                "inputs": inputs,
                "result": result,
            }),
        )
        self.evidence_log.append(ev)
        return ev

    # ============================================================
    # Primitivas de control
    # ============================================================

    def _exec_sequence(self, node: ProgramNode) -> Any:
        """SEQUENCE: ejecuta cada arg en orden, devuelve último."""
        last = None
        for arg in node.args:
            last = self._execute_node(arg)
        return last

    def _exec_bind(self, node: ProgramNode) -> Any:
        """BIND: let name = value."""
        name_node = node.kwargs.get("name")
        value_node = node.kwargs.get("value")
        if not name_node or not value_node:
            raise ExecutionError("BIND requires name and value")
        
        name = self._execute_node(name_node)
        value = self._execute_node(value_node)
        
        if not isinstance(name, str):
            raise ExecutionError(f"BIND name must be string, got {type(name)}")
        
        self.env[name] = value
        return value

    def _exec_value(self, node: ProgramNode) -> Any:
        """VALUE: literal raw."""
        return node.kwargs.get("raw")

    def _exec_reference(self, node: ProgramNode) -> Any:
        """REFERENCE: retrieve a previously bound value."""
        name = node.kwargs.get("name")
        if not isinstance(name, str) or name not in self.env:
            raise ExecutionError(f"Unknown reference: {name!r}")
        return self.env[name]

    def _exec_call(self, node: ProgramNode) -> Any:
        """CALL: ejecuta capability."""
        if not node.args:
            raise ExecutionError("CALL requires capability as first arg")
        
        cap_node = node.args[0]
        capability = self._execute_node(cap_node)
        
        if not isinstance(capability, str):
            raise ExecutionError(f"Capability must be string, got {type(capability)}")
        
        # Evaluar argumentos
        inputs = {}
        for i, arg_node in enumerate(node.args[1:]):
            inputs[f"arg{i}"] = self._execute_node(arg_node)
        
        # Evaluar kwargs
        for k, v_node in node.kwargs.items():
            if k not in ("value",):  # skip internal
                inputs[k] = self._execute_node(v_node)
        
        started = datetime.now(UTC).isoformat()
        
        try:
            result, stdout, stderr = self._capture_streams(
                execute_capability, capability, inputs
            )
            finished = datetime.now(UTC).isoformat()
            
            self._record_evidence(
                node=node, inputs=inputs, result=result,
                stdout=stdout, stderr=stderr,
                started_at=started, finished_at=finished,
            )
            return result
        except Exception as e:
            finished = datetime.now(UTC).isoformat()
            ev = self._record_evidence(
                node=node, inputs=inputs, error=str(e),
                started_at=started, finished_at=finished,
            )
            raise ExecutionError(f"Capability {capability} failed: {e}", ev) from e

    def _exec_if(self, node: ProgramNode) -> Any:
        """IF: cond -> then : else."""
        cond = node.args[0] if node.args else None
        then_branch = node.kwargs.get("then")
        else_branch = node.kwargs.get("else")
        
        if cond is None or then_branch is None:
            raise ExecutionError("IF requires cond and then")
        
        condition = self._execute_node(cond)
        if condition:
            return self._execute_node(then_branch)
        elif else_branch is not None:
            return self._execute_node(else_branch)
        return None

    def _exec_loop(self, node: ProgramNode) -> Any:
        """LOOP: while condition do body."""
        if len(node.args) < 2:
            raise ExecutionError("LOOP requires condition and body")
        
        cond_node, body_node = node.args[0], node.args[1]
        last = None
        max_iterations = 10000  # safety
        
        for _ in range(max_iterations):
            condition = self._execute_node(cond_node)
            if not condition:
                break
            last = self._execute_node(body_node)
        else:
            raise ExecutionError("LOOP exceeded max iterations")
        
        return last

    def _exec_foreach(self, node: ProgramNode) -> Any:
        """FOREACH: for item in iterable do body."""
        if len(node.args) < 2:
            raise ExecutionError("FOREACH requires iterable and body")
        
        iterable_node, body_node = node.args[0], node.args[1]
        iterable = self._execute_node(iterable_node)
        
        if not hasattr(iterable, "__iter__"):
            raise ExecutionError(f"FOREACH iterable must be iterable, got {type(iterable)}")
        
        variable_node = node.kwargs.get("var")
        variable = variable_node.kwargs.get("raw") if isinstance(variable_node, ProgramNode) else "_item"
        if not isinstance(variable, str):
            raise ExecutionError("FOREACH variable must be a string")
        last = None
        for item in iterable:
            self.env[variable] = item
            self.env["_item"] = item
            last = self._execute_node(body_node)
        return last

    def _exec_return(self, node: ProgramNode) -> Any:
        """RETURN: sale con valor."""
        if node.args:
            value = self._execute_node(node.args[0])
            raise ReturnSignal(value)
        raise ReturnSignal(None)

    def _exec_try(self, node: ProgramNode) -> Any:
        """TRY/CATCH/FINALLY."""
        try_body = node.kwargs.get("try")
        catch_body = node.kwargs.get("catch")
        finally_body = node.kwargs.get("finally")
        
        if not try_body:
            raise ExecutionError("TRY requires try body")
        
        try:
            return self._execute_node(try_body)
        except ReturnSignal:
            raise
        except Exception as e:
            if catch_body:
                self.env["_error"] = str(e)
                return self._execute_node(catch_body)
            raise
        finally:
            if finally_body:
                self._execute_node(finally_body)

    def _exec_transaction(self, node: ProgramNode) -> Any:
        paths_node = node.kwargs.get("paths")
        body = node.args[0] if node.args else None
        if not isinstance(paths_node, ProgramNode) or not isinstance(body, ProgramNode):
            raise ExecutionError("TRANSACTION requires paths and body")
        paths = self._execute_node(paths_node)
        if not isinstance(paths, list):
            raise ExecutionError("TRANSACTION paths must be a list")
        root = Path(tempfile.mkdtemp(prefix="intentlang-node-txn-"))
        snapshots: list[tuple[Path, Path | None]] = []
        try:
            for index, raw_path in enumerate(paths):
                target_path = Path(raw_path)
                backup_path = root / str(index)
                if target_path.exists():
                    if target_path.is_dir():
                        shutil.copytree(target_path, backup_path)
                    else:
                        shutil.copy2(target_path, backup_path)
                    snapshots.append((target_path, backup_path))
                else:
                    snapshots.append((target_path, None))
            return self._execute_node(body)
        except ReturnSignal:
            raise
        except Exception:
            for original_path, snapshot_path in reversed(snapshots):
                if original_path.is_dir():
                    shutil.rmtree(original_path)
                elif original_path.exists():
                    original_path.unlink()
                if snapshot_path is not None:
                    original_path.parent.mkdir(parents=True, exist_ok=True)
                    if snapshot_path.is_dir():
                        shutil.copytree(snapshot_path, original_path)
                    else:
                        shutil.copy2(snapshot_path, original_path)
            raise
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def _exec_parallel(self, node: ProgramNode) -> Any:
        """PARALLEL: ejecuta args concurrentemente."""
        max_workers_raw = node.kwargs.get("max_workers", 4)
        max_workers: int = self._execute_node(max_workers_raw) if isinstance(max_workers_raw, ProgramNode) else max_workers_raw
        futures = []
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(self._execute_node, arg) for arg in node.args]
            
            results = []
            for f in as_completed(futures):
                try:
                    results.append(f.result())
                except Exception as e:
                    results.append({"error": str(e)})
        
        return results

    # ============================================================
    # Primitivas de datos
    # ============================================================

    def _exec_compare(self, node: ProgramNode) -> bool:
        """COMPARE: eq, lt, gt, contains."""
        if len(node.args) < 2:
            raise ExecutionError("COMPARE requires two args")
        
        left = self._execute_node(node.args[0])
        right = self._execute_node(node.args[1])
        op_node = node.kwargs.get("op", "eq")
        op = self._execute_node(op_node) if isinstance(op_node, ProgramNode) else op_node
        
        ops = {
            "eq": lambda a, b: a == b,
            "ne": lambda a, b: a != b,
            "lt": lambda a, b: a < b,
            "le": lambda a, b: a <= b,
            "gt": lambda a, b: a > b,
            "ge": lambda a, b: a >= b,
            "contains": lambda a, b: b in a if hasattr(a, "__contains__") else False,
        }
        
        if op not in ops:
            raise ExecutionError(f"Unknown compare op: {op}")
        
        return ops[op](left, right)

    def _exec_map(self, node: ProgramNode) -> list:
        """MAP: transform each."""
        if len(node.args) < 2:
            raise ExecutionError("MAP requires func and iterable")
        
        func_node, iterable_node = node.args[0], node.args[1]
        iterable = self._execute_node(iterable_node)
        
        results = []
        for item in iterable:
            self.env["_item"] = item
            results.append(self._execute_node(func_node))
        return results

    def _exec_filter(self, node: ProgramNode) -> list:
        """FILTER: keep if predicate."""
        if len(node.args) < 2:
            raise ExecutionError("FILTER requires predicate and iterable")
        
        pred_node, iterable_node = node.args[0], node.args[1]
        iterable = self._execute_node(iterable_node)
        
        results = []
        for item in iterable:
            self.env["_item"] = item
            if self._execute_node(pred_node):
                results.append(item)
        return results

    def _exec_collect(self, node: ProgramNode) -> Any:
        """COLLECT/REDUCE: aggregate."""
        if not node.args:
            raise ExecutionError("COLLECT requires iterable")
        
        iterable = self._execute_node(node.args[0])
        reducer = node.args[1] if len(node.args) > 1 else None
        
        if reducer:
            acc = None
            for item in iterable:
                self.env["_item"] = item
                self.env["_acc"] = acc
                acc = self._execute_node(reducer)
            return acc
        return list(iterable)

    def _exec_load(self, node: ProgramNode) -> Any:
        """LOAD: read from source (file, env var, etc.)."""
        source = self._execute_node(node.args[0]) if node.args else None
        if isinstance(source, str) and source.startswith("env:"):
            import os
            return os.environ.get(source[4:], "")
        elif isinstance(source, str):
            from pathlib import Path
            return Path(source).read_text(encoding="utf-8")
        return source

    def _exec_store(self, node: ProgramNode) -> Any:
        """STORE: write to target."""
        if len(node.args) < 2:
            raise ExecutionError("STORE requires target and value")
        
        target = self._execute_node(node.args[0])
        value = self._execute_node(node.args[1])
        
        if isinstance(target, str):
            from pathlib import Path
            Path(target).write_text(str(value), encoding="utf-8")
            return {"stored": True, "target": target}
        return {"stored": False}

    def _exec_project(self, node: ProgramNode) -> dict:
        """PROJECT: select fields from dict."""
        obj = self._execute_node(node.args[0]) if node.args else {}
        fields_raw: Any = node.kwargs.get("fields", [])
        fields = self._execute_node(fields_raw) if isinstance(fields_raw, ProgramNode) else fields_raw
        if isinstance(obj, dict):
            return {k: obj[k] for k in fields if k in obj}
        return {}

    # Fallback para primitivas no implementadas
    def __getattr__(self, name: str) -> Callable:
        if name.startswith("_exec_"):
            primitive = name[6:].upper()
            def not_impl(node: ProgramNode) -> Any:
                raise ExecutionError(f"Primitive {primitive} not implemented yet")
            return not_impl
        raise AttributeError(name)


def execute_program(program: Program, capture_output: bool = True) -> dict:
    """Entry point: ejecuta programa y devuelve resultado + evidence."""
    executor = Executor(capture_output=capture_output)
    return executor.execute(program)
