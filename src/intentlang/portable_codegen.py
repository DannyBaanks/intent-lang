"""Complete source generation for the structured Program IR.

This backend intentionally targets a small, honest subset: filesystem write,
copy, move, delete and process execution, plus sequence, bindings, conditionals,
comparisons and foreach over literal lists. Unsupported nodes fail closed.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from .program import Program, ProgramNode


@dataclass(frozen=True, slots=True)
class PortableSource:
    language: str
    source: str


class PortableCodegenError(ValueError):
    """Raised when a Program IR node is outside the portable subset."""


_C_PROLOGUE = r'''#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int intent_write(const char *path, const char *content) {
    FILE *file = fopen(path, "w");
    if (file == NULL) return 1;
    if (fputs(content, file) == EOF) { fclose(file); return 1; }
    return fclose(file) == 0 ? 0 : 1;
}
static int intent_copy(const char *src, const char *dst) {
    FILE *in = fopen(src, "rb");
    FILE *out = fopen(dst, "wb");
    int ch;
    if (in == NULL || out == NULL) { if (in) fclose(in); if (out) fclose(out); return 1; }
    while ((ch = fgetc(in)) != EOF && fputc(ch, out) != EOF) {}
    if (ferror(in) || ferror(out)) { fclose(in); fclose(out); return 1; }
    fclose(in); return fclose(out) == 0 ? 0 : 1;
}
static int intent_move(const char *src, const char *dst) { return rename(src, dst) == 0 ? 0 : 1; }
static int intent_delete(const char *path) { return remove(path) == 0 ? 0 : 1; }
static int intent_run(const char *command) { return system(command); }
'''

_JAVA_PROLOGUE = '''import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;

public class IntentProgram {
    static void intentWrite(String path, String content) throws Exception { Files.writeString(Path.of(path), content); }
    static void intentCopy(String src, String dst) throws Exception { Files.copy(Path.of(src), Path.of(dst), StandardCopyOption.REPLACE_EXISTING); }
    static void intentMove(String src, String dst) throws Exception { Files.move(Path.of(src), Path.of(dst), StandardCopyOption.REPLACE_EXISTING); }
    static void intentDelete(String path) throws Exception { Files.deleteIfExists(Path.of(path)); }
    static void intentRun(String command) throws Exception {
        String shell = System.getProperty("os.name").toLowerCase().contains("win") ? "cmd" : "sh";
        String flag = shell.equals("cmd") ? "/c" : "-c";
        int exit = new ProcessBuilder(shell, flag, command).inheritIO().start().waitFor();
        if (exit != 0) throw new RuntimeException("command failed: " + exit);
    }
'''


class _CobolRenderer:
    """Render the effect subset using GnuCOBOL-compatible source constructs."""

    MAX_RECORD_SIZE = 4096
    MAX_INPUT_RECORD_SIZE = 8192

    def __init__(self) -> None:
        self.variables: dict[str, str] = {}
        self.bindings: list[tuple[str, str]] = []
        self.files: list[tuple[str, str, str]] = []
        self.variable_input_files: set[str] = set()
        self.tables: list[tuple[str, list[str]]] = []
        self.working_variables: list[str] = []
        self.operations: list[str] = []
        self.try_depth = 0

    @staticmethod
    def literal(raw: Any) -> str:
        if isinstance(raw, str):
            return "'" + raw.replace("'", "''") + "'"
        if isinstance(raw, bool):
            return "1" if raw else "0"
        if isinstance(raw, (int, float)):
            return str(raw)
        raise PortableCodegenError(f"unsupported COBOL literal: {raw!r}")

    def expression(self, node: ProgramNode) -> str:
        if node.primitive == "VALUE":
            return self.literal(node.kwargs.get("raw"))
        if node.primitive == "REFERENCE":
            name = node.kwargs.get("name")
            if not isinstance(name, str) or name not in self.variables:
                raise PortableCodegenError(f"unknown COBOL reference: {name!r}")
            return self.variables[name]
        raise PortableCodegenError(f"unsupported COBOL expression: {node.primitive}")

    def condition(self, node: ProgramNode) -> str:
        if node.primitive != "COMPARE" or len(node.args) != 2:
            raise PortableCodegenError("COBOL conditions require a two-operand COMPARE")
        op_node = node.kwargs.get("op", "eq")
        op = op_node.kwargs.get("raw") if isinstance(op_node, ProgramNode) else op_node
        operators = {"eq": "=", "ne": "NOT =", "lt": "<", "le": "<=", "gt": ">", "ge": ">="}
        if op not in operators:
            raise PortableCodegenError(f"unsupported COBOL comparison: {op!r}")
        left = self.expression(node.args[0])
        right = self.expression(node.args[1])
        return f"FUNCTION TRIM({left}) {operators[op]} FUNCTION TRIM({right})"

    def node(self, node: ProgramNode) -> None:
        if node.primitive == "SEQUENCE":
            for child in node.args:
                self.node(child)
            return
        if node.primitive == "BIND":
            name_node = node.kwargs.get("name")
            value_node = node.kwargs.get("value")
            name = name_node.kwargs.get("raw") if isinstance(name_node, ProgramNode) else None
            if not isinstance(name, str) or not isinstance(value_node, ProgramNode):
                raise PortableCodegenError("invalid COBOL BIND")
            identifier = _identifier(name).upper().replace("_", "-")
            self.variables[name] = identifier
            self.bindings.append((identifier, self.expression(value_node)))
            return
        if node.primitive == "COMPARE":
            self.operations.append("CONTINUE")
            return
        if node.primitive == "IF":
            condition = node.args[0] if node.args else None
            then_body = node.kwargs.get("then")
            else_body = node.kwargs.get("else")
            if not isinstance(condition, ProgramNode) or not isinstance(then_body, ProgramNode):
                raise PortableCodegenError("COBOL IF requires condition and then branch")
            self.operations.append(f"IF {self.condition(condition)}")
            self.node(then_body)
            if isinstance(else_body, ProgramNode):
                self.operations.append("ELSE")
                self.node(else_body)
            self.operations.append("END-IF")
            return
        if node.primitive == "FOREACH":
            if len(node.args) != 2 or node.args[0].primitive != "VALUE":
                raise PortableCodegenError("COBOL FOREACH requires a literal list and body")
            values = node.args[0].kwargs.get("raw")
            body = node.args[1]
            var_node = node.kwargs.get("var")
            name = var_node.kwargs.get("raw") if isinstance(var_node, ProgramNode) else None
            if not isinstance(values, list) or not isinstance(body, ProgramNode) or not isinstance(name, str):
                raise PortableCodegenError("invalid COBOL FOREACH")
            table_name = f"TABLE-{len(self.tables) + 1}"
            index_name = f"INDEX-{len(self.tables) + 1}"
            variable_name = _identifier(name).upper().replace("_", "-")
            self.tables.append((table_name, [self.literal(item) for item in values]))
            self.working_variables.extend([index_name, variable_name])
            self.variables[name] = variable_name
            self.operations.extend([
                f"PERFORM VARYING {index_name} FROM 1 BY 1 UNTIL {index_name} > {len(values)}",
                *self._bound_guard(index_name, len(values), "FOREACH index"),
                f"MOVE {table_name}-VALUE ({index_name}) TO {variable_name}",
            ])
            self.node(body)
            self.operations.append("END-PERFORM")
            return
        if node.primitive == "RETURN":
            if not node.args:
                self.operations.append("MOVE 1 TO WS-RETURN-PENDING" if self.try_depth else "GOBACK")
                return
            value = node.args[0]
            raw = value.kwargs.get("raw") if value.primitive == "VALUE" else None
            if not isinstance(raw, (int, float)):
                raise PortableCodegenError("COBOL RETURN currently requires a numeric literal")
            if self.try_depth:
                self.operations.extend([f"MOVE {self.literal(raw)} TO WS-RETURN", "MOVE 1 TO WS-RETURN-PENDING"])
            else:
                self.operations.append(f"GOBACK RETURNING {self.literal(raw)}")
            return
        if node.primitive == "TRY":
            try_body = node.kwargs.get("try")
            catch = node.kwargs.get("catch")
            finally_body = node.kwargs.get("finally")
            if not isinstance(try_body, ProgramNode):
                raise PortableCodegenError("COBOL TRY requires a body")
            self.operations.append("MOVE 0 TO WS-ERROR")
            self.try_depth += 1
            self.node(try_body)
            if isinstance(catch, ProgramNode):
                self.operations.append("IF WS-ERROR NOT = 0")
                self.node(catch)
                self.operations.append("END-IF")
            if isinstance(finally_body, ProgramNode):
                self.node(finally_body)
            self.try_depth -= 1
            return
        if node.primitive == "TRANSACTION":
            paths_node = node.kwargs.get("paths")
            transaction_body = node.args[0] if node.args else None
            paths = paths_node.kwargs.get("raw") if isinstance(paths_node, ProgramNode) else None
            if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths) or not isinstance(transaction_body, ProgramNode):
                raise PortableCodegenError("COBOL TRANSACTION requires literal paths and a body")
            backups = [f"{path}.intentlang.bak" for path in paths]
            self.operations.append("MOVE 0 TO WS-ERROR")
            for path, backup in zip(paths, backups, strict=True):
                self.operations.append(f"CALL 'CBL-COPY-FILE' USING {self.literal(path)} {self.literal(backup)} RETURNING WS-ERROR")
            self.node(transaction_body)
            self.operations.append("IF WS-ERROR NOT = 0")
            for path, backup in zip(paths, backups, strict=True):
                self.operations.append(f"CALL 'CBL-COPY-FILE' USING {self.literal(backup)} {self.literal(path)} RETURNING WS-ERROR")
            self.operations.append("END-IF")
            for backup in backups:
                self.operations.append(f"CALL 'CBL-DELETE-FILE' USING {self.literal(backup)} RETURNING WS-ERROR")
            return
        if node.primitive != "CALL":
            raise PortableCodegenError(f"unsupported COBOL program node: {node.primitive}")
        cap_node = node.args[0] if node.args else None
        capability = cap_node.kwargs.get("raw") if isinstance(cap_node, ProgramNode) else None
        args = {key: self.expression(value) for key, value in node.kwargs.items() if isinstance(value, ProgramNode)}
        if capability == "cap.fs.write":
            self._require(args, capability, "path", "content")
            index = len(self.files) + 1
            file_name = f"OUT-FILE-{index}"
            record_name = f"OUT-REC-{index}"
            self.files.append((file_name, record_name, args["path"]))
            self.operations.extend([
                f"OPEN OUTPUT {file_name}",
                *self._status_guard("OPEN"),
                *self._size_guard(args["content"], "WS-MAX-RECORD-SIZE", "WRITE record"),
                f"MOVE {args['content']} TO {record_name}",
                f"WRITE {record_name}",
                *self._status_guard("WRITE"),
                f"CLOSE {file_name}",
                *self._status_guard("CLOSE"),
            ])
        elif capability == "cap.fs.read":
            self._require(args, capability, "path")
            index = len(self.files) + 1
            file_name = f"IN-FILE-{index}"
            record_name = f"IN-REC-{index}"
            self.files.append((file_name, record_name, args["path"]))
            self.variable_input_files.add(file_name)
            self.operations.extend([
                f"OPEN INPUT {file_name}",
                *self._status_guard("OPEN"),
                f"READ {file_name} INTO {record_name}",
                *self._status_guard("READ"),
                *self._bound_guard("WS-INPUT-SIZE", "WS-MAX-RECORD-SIZE", "READ record"),
                f"DISPLAY {record_name}",
                f"CLOSE {file_name}",
                *self._status_guard("CLOSE"),
            ])
        elif capability in {"cap.fs.copy", "cap.fs.move"}:
            self._require(args, capability, "src", "dst")
            routine = "CBL-COPY-FILE" if capability.endswith("copy") else "CBL-RENAME-FILE"
            self.operations.append(f"CALL '{routine}' USING {args['src']} {args['dst']} RETURNING WS-ERROR")
        elif capability == "cap.fs.delete":
            self._require(args, capability, "path")
            self.operations.append(f"CALL 'CBL-DELETE-FILE' USING {args['path']} RETURNING WS-ERROR")
        elif capability == "cap.process.run":
            self._require(args, capability, "cmd")
            self.operations.append(f"CALL 'SYSTEM' USING {args['cmd']} RETURNING WS-ERROR")
        else:
            raise PortableCodegenError(f"unsupported COBOL capability: {capability!r}")

    def _require(self, args: dict[str, str], capability: str, *names: str) -> None:
        missing = [name for name in names if name not in args]
        if missing:
            raise PortableCodegenError(f"missing inputs for {capability}: {', '.join(missing)}")

    @staticmethod
    def _status_guard(operation: str) -> list[str]:
        return [
            "IF WS-FILE-STATUS NOT = '00'",
            f"DISPLAY 'CRITICAL: FILE STATUS VIOLATION - {operation}'",
            "MOVE 99 TO RETURN-CODE",
            "MOVE 1 TO WS-ERROR",
            "STOP RUN",
            "END-IF",
        ]

    @staticmethod
    def _size_guard(expression: str, maximum: str, label: str) -> list[str]:
        return [
            f"IF FUNCTION LENGTH({expression}) > {maximum}",
            f"DISPLAY 'CRITICAL: SEMANTIC INVARIANT VIOLATION - {label} OUT OF BOUNDS'",
            "MOVE 99 TO RETURN-CODE",
            "STOP RUN",
            "END-IF",
        ]

    @staticmethod
    def _bound_guard(expression: str, maximum: str | int, label: str) -> list[str]:
        return [
            f"IF {expression} > {maximum}",
            f"DISPLAY 'CRITICAL: SEMANTIC INVARIANT VIOLATION - {label} OUT OF BOUNDS'",
            "MOVE 99 TO RETURN-CODE",
            "STOP RUN",
            "END-IF",
        ]

    def render(self, program: Program) -> PortableSource:
        self.node(program.root)
        lines = [
            "IDENTIFICATION DIVISION.", "PROGRAM-ID. INTENTPROGRAM.",
            "ENVIRONMENT DIVISION.", "INPUT-OUTPUT SECTION.", "FILE-CONTROL.",
        ]
        for file_name, _, path in self.files:
            lines.extend([f"    SELECT {file_name} ASSIGN TO {path}", "        ORGANIZATION IS LINE SEQUENTIAL", "        FILE STATUS IS WS-FILE-STATUS."])
        lines.extend(["DATA DIVISION.", "FILE SECTION."])
        for file_name, record_name, _ in self.files:
            if file_name in self.variable_input_files:
                lines.extend([
                    f"FD {file_name}",
                    f"    RECORD IS VARYING IN SIZE FROM 1 TO {self.MAX_INPUT_RECORD_SIZE} CHARACTERS",
                    "    DEPENDING ON WS-INPUT-SIZE.",
                    f"01 {record_name} PIC X({self.MAX_INPUT_RECORD_SIZE}).",
                ])
            else:
                lines.extend([f"FD {file_name}.", f"01 {record_name} PIC X(4096)."])
        lines.extend([
            "WORKING-STORAGE SECTION.",
            "01 WS-ERROR PIC S9(9) COMP-5 VALUE 0.",
            "01 WS-FILE-STATUS PIC XX VALUE '00'.",
            f"01 WS-MAX-RECORD-SIZE PIC 9(9) COMP-5 VALUE {self.MAX_RECORD_SIZE}.",
            "01 WS-INPUT-SIZE PIC 9(9) COMP-5 VALUE 0.",
            "01 WS-RETURN PIC S9(9) COMP-5 VALUE 0.",
            "01 WS-RETURN-PENDING PIC 9 VALUE 0.",
        ])
        for table_name, values in self.tables:
            lines.append(f"01 {table_name}.")
            lines.append(f"    05 {table_name}-VALUE PIC X(4096) OCCURS {len(values)} TIMES.")
        bound_names = {name for name, _ in self.bindings}
        lines.extend(
            f"01 {identifier} PIC X(4096)."
            for identifier in self.working_variables
            if identifier not in bound_names
        )
        for identifier, value in self.bindings:
            lines.append(f"01 {identifier} PIC X(4096) VALUE {value}.")
        initializers: list[str] = []
        for table_name, values in self.tables:
            for index, value in enumerate(values, 1):
                initializers.extend(self._size_guard(value, "WS-MAX-RECORD-SIZE", "FOREACH item"))
                initializers.append(f"MOVE {value} TO {table_name}-VALUE ({index})")
        operations = (*initializers, *self.operations, "IF WS-RETURN-PENDING = 1", "GOBACK RETURNING WS-RETURN", "END-IF")
        lines.extend(["PROCEDURE DIVISION.", *[f"    {operation}" for operation in operations], "    GOBACK."])
        return PortableSource("cobol", "\n".join(lines) + "\n")


def _identifier(name: str) -> str:
    result = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if not result or result[0].isdigit():
        result = "v_" + result
    return result


class _Renderer:
    def __init__(self, language: str) -> None:
        if language not in {"c", "java"}:
            raise PortableCodegenError(f"unsupported portable target: {language}")
        self.language = language
        self.lines: list[str] = []
        self.indent = 1
        self.variables: dict[str, str] = {}
        self.list_variables: dict[str, str] = {}
        self.temp_counter = 0
        self.try_depth = 0

    def emit(self, line: str = "") -> None:
        self.lines.append("    " * self.indent + line)

    def literal(self, raw: Any) -> str:
        if isinstance(raw, bool):
            return "1" if self.language == "c" else ("true" if raw else "false")
        if raw is None:
            return "NULL" if self.language == "c" else "null"
        if isinstance(raw, (int, float)):
            return repr(raw)
        if isinstance(raw, str):
            return json.dumps(raw, ensure_ascii=False)
        raise PortableCodegenError(f"unsupported literal: {raw!r}")

    def expression(self, node: ProgramNode) -> str:
        if node.primitive == "VALUE":
            return self.literal(node.kwargs.get("raw"))
        if node.primitive == "REFERENCE":
            name = node.kwargs.get("name")
            if not isinstance(name, str) or name not in self.variables:
                raise PortableCodegenError(f"unknown reference: {name!r}")
            return self.variables[name]
        if node.primitive == "COMPARE":
            if len(node.args) != 2:
                raise PortableCodegenError("COMPARE requires two operands")
            left, right = self.expression(node.args[0]), self.expression(node.args[1])
            op_node = node.kwargs.get("op", "eq")
            op = op_node.kwargs.get("raw") if isinstance(op_node, ProgramNode) else op_node
            if op not in {"eq", "ne", "lt", "le", "gt", "ge"}:
                raise PortableCodegenError(f"unsupported comparison: {op!r}")
            if self.language == "c":
                operator = {"eq": "==", "ne": "!=", "lt": "<", "le": "<=", "gt": ">", "ge": ">="}[op]
                return f"strcmp({left}, {right}) {operator} 0"
            operator = {"eq": ".equals", "ne": "!"}[op] if op in {"eq", "ne"} else {"lt": "compareTo", "le": "compareTo", "gt": "compareTo", "ge": "compareTo"}[op]
            if op == "eq":
                return f"{left}.equals({right})"
            if op == "ne":
                return f"!{left}.equals({right})"
            comparator = {"lt": "< 0", "le": "<= 0", "gt": "> 0", "ge": ">= 0"}[op]
            return f"{left}.compareTo({right}) {comparator}"
        raise PortableCodegenError(f"node is not an expression: {node.primitive}")

    def call(self, node: ProgramNode) -> None:
        cap_node = node.args[0] if node.args else None
        capability = cap_node.kwargs.get("raw") if isinstance(cap_node, ProgramNode) else None
        args = {key: self.expression(value) for key, value in node.kwargs.items() if isinstance(value, ProgramNode)}
        functions = {
            "cap.fs.write": ("intent_write", ("path", "content")),
            "cap.fs.copy": ("intent_copy", ("src", "dst")),
            "cap.fs.move": ("intent_move", ("src", "dst")),
            "cap.fs.delete": ("intent_delete", ("path",)),
            "cap.process.run": ("intent_run", ("cmd",)),
        }
        if capability not in functions:
            raise PortableCodegenError(f"unsupported portable capability: {capability!r}")
        function, names = functions[capability]
        if self.language == "java":
            function = {
                "intent_write": "intentWrite",
                "intent_copy": "intentCopy",
                "intent_move": "intentMove",
                "intent_delete": "intentDelete",
                "intent_run": "intentRun",
            }[function]
        missing = [name for name in names if name not in args]
        if missing:
            raise PortableCodegenError(f"missing inputs for {capability}: {', '.join(missing)}")
        invocation = f"{function}({', '.join(args[name] for name in names)})"
        if self.language == "c" and self.try_depth:
            self.emit(f"if ({invocation} != 0) intentError = 1;")
        else:
            self.emit(f"if ({invocation} != 0) return 1;" if self.language == "c" else f"{invocation};")

    def node(self, node: ProgramNode) -> None:
        if node.primitive == "SEQUENCE":
            for child in node.args:
                self.node(child)
        elif node.primitive == "BIND":
            name_node, value_node = node.kwargs.get("name"), node.kwargs.get("value")
            name = name_node.kwargs.get("raw") if isinstance(name_node, ProgramNode) else None
            if not isinstance(name, str) or not isinstance(value_node, ProgramNode):
                raise PortableCodegenError("invalid BIND")
            identifier = _identifier(name)
            if value_node.primitive == "VALUE" and isinstance(value_node.kwargs.get("raw"), list):
                values = value_node.kwargs["raw"]
                rendered = ", ".join(self.literal(item) for item in values)
                if self.language == "c":
                    self.emit(f"const char *{identifier}[] = {{{rendered}}};")
                    self.emit(f"size_t {identifier}_len = {len(values)};")
                else:
                    self.emit(f"String[] {identifier} = {{{rendered}}};")
                self.list_variables[name] = identifier
                self.variables[name] = identifier
            else:
                rendered = self.expression(value_node)
                if self.language == "c":
                    self.emit(f"const char *{identifier} = {rendered};")
                else:
                    self.emit(f"String {identifier} = {rendered};")
                self.variables[name] = identifier
        elif node.primitive == "CALL":
            self.call(node)
        elif node.primitive == "COMPARE":
            if self.language == "c":
                self.emit(f"(void)({self.expression(node)});")
            else:
                self.temp_counter += 1
                self.emit(f"boolean intentComparison{self.temp_counter} = {self.expression(node)};")
        elif node.primitive == "IF":
            condition = node.args[0] if node.args else None
            then_branch = node.kwargs.get("then")
            else_branch = node.kwargs.get("else")
            if not isinstance(condition, ProgramNode) or not isinstance(then_branch, ProgramNode):
                raise PortableCodegenError("IF requires condition and then branch")
            self.emit(f"if ({self.expression(condition)}) {{")
            self.indent += 1
            self.node(then_branch)
            self.indent -= 1
            if isinstance(else_branch, ProgramNode):
                self.emit("} else {")
                self.indent += 1
                self.node(else_branch)
                self.indent -= 1
            self.emit("}")
        elif node.primitive == "FOREACH":
            iterable, body = (*node.args, None, None)[:2]
            variable_node = node.kwargs.get("var")
            name = variable_node.kwargs.get("raw") if isinstance(variable_node, ProgramNode) else None
            if not isinstance(iterable, ProgramNode) or not isinstance(body, ProgramNode) or not isinstance(name, str):
                raise PortableCodegenError("FOREACH requires iterable, variable and body")
            if iterable.primitive != "VALUE" or not isinstance(iterable.kwargs.get("raw"), list):
                raise PortableCodegenError("portable FOREACH requires a literal list")
            identifier = _identifier(name)
            values = iterable.kwargs["raw"]
            if self.language == "c":
                self.emit(f"for (size_t i = 0; i < {len(values)}; ++i) {{")
                self.indent += 1
                self.emit(f"const char *{identifier} = {self.literal(values[0]) if values else 'NULL'};")
                if values:
                    self.emit(f"const char *{identifier}_values[] = {{{', '.join(self.literal(item) for item in values)}}};")
                    self.emit(f"{identifier} = {identifier}_values[i];")
            else:
                self.emit(f"for (String {identifier} : new String[] {{{', '.join(self.literal(item) for item in values)}}}) {{")
                self.indent += 1
            self.variables[name] = identifier
            self.node(body)
            self.indent -= 1
            self.emit("}")
        elif node.primitive == "RETURN":
            if self.language == "c":
                self.emit("return 0;")
            else:
                self.emit("return;")
        elif node.primitive == "TRY":
            body = node.kwargs.get("try")
            catch = node.kwargs.get("catch")
            finally_body = node.kwargs.get("finally")
            if not isinstance(body, ProgramNode):
                raise PortableCodegenError("TRY requires a body")
            if self.language == "c":
                self.emit("int intentError = 0;")
                self.try_depth += 1
                self.node(body)
                self.try_depth -= 1
                if isinstance(catch, ProgramNode):
                    self.emit("if (intentError) {")
                    self.indent += 1
                    self.node(catch)
                    self.indent -= 1
                    self.emit("}")
                if isinstance(finally_body, ProgramNode):
                    self.node(finally_body)
            else:
                self.emit("try {")
                self.indent += 1
                self.node(body)
                self.indent -= 1
                if isinstance(catch, ProgramNode):
                    self.emit("} catch (Exception intentError) {")
                    self.indent += 1
                    self.node(catch)
                    self.indent -= 1
                if isinstance(finally_body, ProgramNode):
                    self.emit("} finally {")
                    self.indent += 1
                    self.node(finally_body)
                    self.indent -= 1
                self.emit("}")
        else:
            raise PortableCodegenError(f"unsupported portable node: {node.primitive}")

    def render(self, program: Program) -> PortableSource:
        if self.language == "c":
            self.lines = list(_C_PROLOGUE.splitlines())
            self.emit("int main(void) {")
        else:
            self.lines = list(_JAVA_PROLOGUE.splitlines())
            self.emit("public static void main(String[] args) throws Exception {")
        self.node(program.root)
        self.emit("return 0;" if self.language == "c" else "")
        self.indent -= 1
        self.emit("}")
        if self.language == "java":
            self.lines.append("}")
        return PortableSource(self.language, "\n".join(self.lines) + "\n")


def generate_program_source(program: Program, language: str) -> PortableSource:
    """Generate a complete compilable C or Java program from Program IR."""
    if language == "cobol":
        return _CobolRenderer().render(program)
    return _Renderer(language).render(program)
