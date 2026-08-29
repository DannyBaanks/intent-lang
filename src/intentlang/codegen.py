"""Codegen Semantic Capability: Intent IR → Target Language Code.

Capability semántica que traduce Intent IR a código en lenguaje objetivo
(Python, Rust, Malbolge, etc.) verificando relación semántica.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TypedDict

from .program import Program


@dataclass(frozen=True, slots=True)
class CodegenResult:
    """Resultado de generación de código."""
    language: str
    primitive: str
    code: str
    ast: dict | None = None
    verified: bool = True
    semantic_score: float = 1.0


# ============================================================
# Quoting por lenguaje
# ============================================================

def quote_for_language(value: str, language: str) -> str:
    """Escapa y cita un valor según el lenguaje objetivo."""
    if language == "python":
        # Python: usar repr() para quoting seguro
        return repr(value)
    elif language == "rust":
        # Rust: comillas dobles, escapar comillas y backslashes
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    elif language == "malbolge":
        # Malbolge: sin comillas, solo el valor crudo
        return value
    elif language in ("c", "java"):
        return json.dumps(value, ensure_ascii=False)
    elif language == "cobol":
        return "'" + value.replace("'", "''") + "'"
    else:
        # Default: quoting tipo Python
        return repr(value)


# ============================================================
# Mapeo Primitiva → Operaciones por Lenguaje
# ============================================================

class LanguageMapping(TypedDict, total=False):
    op: str
    template: str
    imports: list[str]
    hook: bool
    verified: bool
    allow_unverified: bool


# Estructura: {primitiva: {lenguaje: {"op": "...", "template": "...", "imports": [...]}}}
PRIMITIVE_TO_LANG_OP: dict[str, dict[str, LanguageMapping]] = {
    # EFECTOS
    "COPY": {
        "python": {
            "op": "shutil.copy2",
            "template": "shutil.copy2({src}, {dst})",
            "imports": ["import shutil"],
        },
        "rust": {
            "op": "std::fs::copy",
            "template": "std::fs::copy({src}, {dst})?;",
            "imports": ["use std::fs;"],
        },
        "malbolge": {
            "op": "MALBOLGE_COPY",
            "template": "(MALBOLGE_COPY {src} {dst})",
            "imports": [],
        },
    },
    "MOVE": {
        "python": {
            "op": "shutil.move",
            "template": "shutil.move({src}, {dst})",
            "imports": ["import shutil"],
        },
        "rust": {
            "op": "std::fs::rename",
            "template": "std::fs::rename({src}, {dst})?;",
            "imports": ["use std::fs;"],
        },
        "malbolge": {
            "op": "MALBOLGE_MOVE",
            "template": "(MALBOLGE_MOVE {src} {dst})",
            "imports": [],
        },
    },
    "REMOVE": {
        "python": {
            "op": "os.remove / shutil.rmtree",
            "template": "import os, shutil\nif os.path.isdir({path}): shutil.rmtree({path})\nelse: os.remove({path})",
            "imports": ["import os", "import shutil"],
        },
        "rust": {
            "op": "std::fs::remove_file / std::fs::remove_dir_all",
            "template": "if {path}.is_dir() { std::fs::remove_dir_all({path})?; } else { std::fs::remove_file({path})?; }",
            "imports": ["use std::fs;", "use std::path::Path;"],
        },
        "malbolge": {
            "op": "MALBOLGE_DELETE",
            "template": "(MALBOLGE_DELETE {path})",
            "imports": [],
        },
    },
    "RUN": {
        "python": {
            "op": "subprocess.run",
            "template": "subprocess.run({cmd}, shell=True, check=True)",
            "imports": ["import subprocess"],
        },
        "rust": {
            "op": "std::process::Command",
            "template": "std::process::Command::new(\"sh\").arg(\"-c\").arg({cmd}).status()?;",
            "imports": ["use std::process::Command;"],
        },
        "malbolge": {
            "op": "MALBOLGE_EXEC",
            "template": "(MALBOLGE_EXEC {cmd})",
            "imports": [],
        },
    },
    "QUERY": {
        "python": {
            "op": "sqlite3 / custom",
            "template": "# query implementation depends on backend",
            "imports": [],
        },
        "rust": {
            "op": "sqlx / diesel",
            "template": "// query implementation depends on backend",
            "imports": [],
        },
        "malbolge": {
            "op": "MALBOLGE_QUERY",
            "template": "(MALBOLGE_QUERY {query})",
            "imports": [],
        },
    },
    "DOWNLOAD": {
        "python": {
            "op": "urllib.request.urlretrieve",
            "template": "urllib.request.urlretrieve({url}, {dest})",
            "imports": ["import urllib.request"],
        },
        "rust": {
            "op": "reqwest::get",
            "template": "let resp = reqwest::get({url}).await?; let mut dest = std::fs::File::create({dest})?; resp.copy_to(&mut dest).await?;",
            "imports": ["use reqwest;", "use std::fs::File;", "use std::io::copy;"],
        },
        "malbolge": {
            "op": "MALBOLGE_DOWNLOAD",
            "template": "(MALBOLGE_DOWNLOAD {url} {dest})",
            "imports": [],
        },
    },
    "COMPILE": {
        "python": {
            "op": "py_compile / subprocess",
            "template": "import py_compile\npy_compile.compile({source}, cfile={output})",
            "imports": ["import py_compile"],
        },
        "rust": {
            "op": "rustc / cargo",
            "template": "std::process::Command::new(\"rustc\").arg({source}).arg(\"-o\").arg({output}).status()?;",
            "imports": ["use std::process::Command;"],
        },
        "malbolge": {
            "op": "MALBOLGE_COMPILE",
            "template": "(MALBOLGE_COMPILE {source} {output})",
            "imports": [],
        },
    },
    "WRITE": {
        "python": {
            "op": "open().write()",
            "template": "with open({path}, 'w') as f: f.write({content})",
            "imports": [],
        },
        "rust": {
            "op": "std::fs::write",
            "template": "std::fs::write({path}, {content})?;",
            "imports": ["use std::fs;"],
        },
        "malbolge": {
            "op": "MALBOLGE_WRITE",
            "template": "(MALBOLGE_WRITE {path} {content})",
            "imports": [],
        },
    },
    "READ": {
        "python": {
            "op": "open().read()",
            "template": "with open({path}) as f: content = f.read()",
            "imports": [],
        },
        "rust": {
            "op": "std::fs::read_to_string",
            "template": "let content = std::fs::read_to_string({path})?;",
            "imports": ["use std::fs;"],
        },
        "malbolge": {
            "op": "MALBOLGE_READ",
            "template": "(MALBOLGE_READ {path})",
            "imports": [],
        },
    },
}

# Portable first-class targets. These templates are deliberately standalone
# snippets/programs so their output can be compiled independently in smoke
# tests instead of being mistaken for pseudocode.
_PORTABLE_TARGETS: dict[str, dict[str, LanguageMapping]] = {
    "COPY": {
        "c": {
            "op": "fopen/fread",
            "template": '#include <stdio.h>\nint main(void) { FILE *in = fopen({src}, "rb"); FILE *out = fopen({dst}, "wb"); if (!in || !out) return 1; int c; while ((c = fgetc(in)) != EOF) fputc(c, out); fclose(in); fclose(out); return 0; }',
            "imports": [],
        },
        "java": {
            "op": "Files.copy",
            "template": 'import java.nio.file.Files;\nimport java.nio.file.Path;\nimport java.nio.file.StandardCopyOption;\npublic class IntentProgram { public static void main(String[] args) throws Exception { Files.copy(Path.of({src}), Path.of({dst}), StandardCopyOption.REPLACE_EXISTING); } }',
            "imports": [],
        },
    },
    "MOVE": {
        "c": {
            "op": "rename",
            "template": '#include <stdio.h>\nint main(void) { return rename({src}, {dst}) == 0 ? 0 : 1; }',
            "imports": [],
        },
        "java": {
            "op": "Files.move",
            "template": 'import java.nio.file.Files;\nimport java.nio.file.Path;\nimport java.nio.file.StandardCopyOption;\npublic class IntentProgram { public static void main(String[] args) throws Exception { Files.move(Path.of({src}), Path.of({dst}), StandardCopyOption.REPLACE_EXISTING); } }',
            "imports": [],
        },
    },
    "DELETE": {
        "c": {
            "op": "remove",
            "template": '#include <stdio.h>\nint main(void) { return remove({path}) == 0 ? 0 : 1; }',
            "imports": [],
        },
        "java": {
            "op": "Files.deleteIfExists",
            "template": 'import java.nio.file.Files;\nimport java.nio.file.Path;\npublic class IntentProgram { public static void main(String[] args) throws Exception { Files.deleteIfExists(Path.of({path})); } }',
            "imports": [],
        },
    },
    "REMOVE": {
        "c": {
            "op": "remove",
            "template": '#include <stdio.h>\nint main(void) { return remove({path}) == 0 ? 0 : 1; }',
            "imports": [],
        },
        "java": {
            "op": "Files.deleteIfExists",
            "template": 'import java.nio.file.Files;\nimport java.nio.file.Path;\npublic class IntentProgram { public static void main(String[] args) throws Exception { Files.deleteIfExists(Path.of({path})); } }',
            "imports": [],
        },
    },
    "RUN": {
        "c": {
            "op": "system",
            "template": '#include <stdlib.h>\nint main(void) { return system({cmd}); }',
            "imports": [],
        },
        "java": {
            "op": "ProcessBuilder",
            "template": 'public class IntentProgram { public static void main(String[] args) throws Exception { int exit = new ProcessBuilder("sh", "-c", {cmd}).inheritIO().start().waitFor(); if (exit != 0) throw new RuntimeException("command failed: " + exit); } }',
            "imports": [],
        },
    },
    "WRITE": {
        "c": {
            "op": "fopen/fputs",
            "template": '#include <stdio.h>\nint main(void) { FILE *f = fopen({path}, "w"); if (!f) return 1; fputs({content}, f); fclose(f); return 0; }',
            "imports": [],
        },
        "java": {
            "op": "Files.writeString",
            "template": 'import java.nio.file.Files;\nimport java.nio.file.Path;\npublic class IntentProgram { public static void main(String[] args) throws Exception { Files.writeString(Path.of({path}), {content}); } }',
            "imports": [],
        },
    },
    "READ": {
        "c": {
            "op": "fopen/fread",
            "template": '#include <stdio.h>\nint main(void) { FILE *f = fopen({path}, "r"); if (!f) return 1; int c; while ((c = fgetc(f)) != EOF) putchar(c); fclose(f); return 0; }',
            "imports": [],
        },
        "java": {
            "op": "Files.readString",
            "template": 'import java.nio.file.Files;\nimport java.nio.file.Path;\npublic class IntentProgram { public static void main(String[] args) throws Exception { System.out.print(Files.readString(Path.of({path}))); } }',
            "imports": [],
        },
    },
}

# COBOL is exposed as a public integration hook for capabilities that do not
# yet have a standalone source template. It does not assume a private runtime.
_COBOL_HOOK: LanguageMapping = {
    "op": "GnuCOBOL integration hook",
    "template": "*> TODO(cobol-backend): bind {operation} to a public runtime runner.\n       IDENTIFICATION DIVISION.\n       PROGRAM-ID. INTENT-HOOK.\n       PROCEDURE DIVISION.\n           *> Inputs are supplied by the caller.\n           *> Implement and verify this capability before enabling it.\n           GOBACK.\n",
    "imports": [],
    "hook": True,
}
_COBOL_OPERANDS = {
    "COPY": "COPY src dst", "MOVE": "MOVE src dst", "DELETE": "DELETE path",
    "REMOVE": "REMOVE path", "RUN": "RUN cmd", "WRITE": "WRITE path content",
    "READ": "READ path", "QUERY": "QUERY query", "DOWNLOAD": "DOWNLOAD url dest",
    "COMPILE": "COMPILE source output",
}
for _primitive, _operation in _COBOL_OPERANDS.items():
    _mapping: LanguageMapping = {**_COBOL_HOOK}
    _mapping["template"] = _mapping["template"].replace("{operation}", _operation)
    PRIMITIVE_TO_LANG_OP.setdefault(_primitive, {})["cobol"] = _mapping

_COBOL_REAL: dict[str, LanguageMapping] = {
    "WRITE": {
        "op": "OPEN OUTPUT / WRITE",
        "template": "IDENTIFICATION DIVISION.\nPROGRAM-ID. INTENTPROGRAM.\nENVIRONMENT DIVISION.\nINPUT-OUTPUT SECTION.\nFILE-CONTROL.\n    SELECT OUT-FILE ASSIGN TO {path}\n        ORGANIZATION IS LINE SEQUENTIAL.\nDATA DIVISION.\nFILE SECTION.\nFD OUT-FILE.\n01 OUT-REC PIC X(4096).\nWORKING-STORAGE SECTION.\n01 CONTENT PIC X(4096) VALUE {content}.\nPROCEDURE DIVISION.\n    OPEN OUTPUT OUT-FILE\n    MOVE CONTENT TO OUT-REC\n    WRITE OUT-REC\n    CLOSE OUT-FILE\n    GOBACK.\n",
        "imports": [], "verified": False, "allow_unverified": True,
    },
    "READ": {
        "op": "OPEN INPUT / READ",
        "template": "IDENTIFICATION DIVISION.\nPROGRAM-ID. INTENTPROGRAM.\nENVIRONMENT DIVISION.\nINPUT-OUTPUT SECTION.\nFILE-CONTROL.\n    SELECT IN-FILE ASSIGN TO {path}\n        ORGANIZATION IS LINE SEQUENTIAL.\nDATA DIVISION.\nFILE SECTION.\nFD IN-FILE.\n01 IN-REC PIC X(4096).\nWORKING-STORAGE SECTION.\n01 EOF-FLAG PIC X VALUE 'N'.\nPROCEDURE DIVISION.\n    OPEN INPUT IN-FILE\n    PERFORM UNTIL EOF-FLAG = 'Y'\n        READ IN-FILE\n            AT END MOVE 'Y' TO EOF-FLAG\n            NOT AT END DISPLAY IN-REC\n        END-READ\n    END-PERFORM\n    CLOSE IN-FILE\n    GOBACK.\n",
        "imports": [], "verified": False, "allow_unverified": True,
    },
    "RUN": {
        "op": "CALL SYSTEM",
        "template": "IDENTIFICATION DIVISION.\nPROGRAM-ID. INTENTPROGRAM.\nDATA DIVISION.\nWORKING-STORAGE SECTION.\n01 COMMAND PIC X(4096) VALUE {cmd}.\n01 EXIT-STATUS PIC S9(9) COMP-5.\nPROCEDURE DIVISION.\n    CALL 'SYSTEM' USING COMMAND RETURNING EXIT-STATUS\n    IF EXIT-STATUS NOT = 0\n        DISPLAY 'COMMAND FAILED' UPON SYSERR\n        GOBACK RETURNING 1\n    END-IF\n    GOBACK.\n",
        "imports": [], "verified": False, "allow_unverified": True,
    },
    "COPY": {
        "op": "CBL_COPY_FILE",
        "template": "IDENTIFICATION DIVISION.\nPROGRAM-ID. INTENTPROGRAM.\nDATA DIVISION.\nWORKING-STORAGE SECTION.\n01 SOURCE-NAME PIC X(1024) VALUE {src}.\n01 DEST-NAME PIC X(1024) VALUE {dst}.\n01 EXIT-STATUS PIC S9(9) COMP-5.\nPROCEDURE DIVISION.\n    CALL 'CBL_COPY_FILE' USING SOURCE-NAME DEST-NAME RETURNING EXIT-STATUS\n    GOBACK RETURNING EXIT-STATUS.\n",
        "imports": [], "verified": False, "allow_unverified": True,
    },
    "MOVE": {
        "op": "CBL_RENAME_FILE",
        "template": "IDENTIFICATION DIVISION.\nPROGRAM-ID. INTENTPROGRAM.\nDATA DIVISION.\nWORKING-STORAGE SECTION.\n01 SOURCE-NAME PIC X(1024) VALUE {src}.\n01 DEST-NAME PIC X(1024) VALUE {dst}.\n01 EXIT-STATUS PIC S9(9) COMP-5.\nPROCEDURE DIVISION.\n    CALL 'CBL_RENAME_FILE' USING SOURCE-NAME DEST-NAME RETURNING EXIT-STATUS\n    GOBACK RETURNING EXIT-STATUS.\n",
        "imports": [], "verified": False, "allow_unverified": True,
    },
    "DELETE": {
        "op": "CBL_DELETE_FILE",
        "template": "IDENTIFICATION DIVISION.\nPROGRAM-ID. INTENTPROGRAM.\nDATA DIVISION.\nWORKING-STORAGE SECTION.\n01 FILE-NAME PIC X(1024) VALUE {path}.\n01 EXIT-STATUS PIC S9(9) COMP-5.\nPROCEDURE DIVISION.\n    CALL 'CBL_DELETE_FILE' USING FILE-NAME RETURNING EXIT-STATUS\n    GOBACK RETURNING EXIT-STATUS.\n",
        "imports": [], "verified": False, "allow_unverified": True,
    },
}
for _primitive, _mapping in _COBOL_REAL.items():
    PRIMITIVE_TO_LANG_OP[_primitive]["cobol"] = _mapping
for _primitive, _targets in _PORTABLE_TARGETS.items():
    PRIMITIVE_TO_LANG_OP.setdefault(_primitive, {}).update(_targets)


def _quote_value(value: str, language: str) -> str:
    """Escapa y cita un valor según el lenguaje objetivo."""
    if language == "python":
        return repr(value)
    elif language == "rust":
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    elif language == "malbolge":
        return value
    else:
        return repr(value)


# ============================================================
# Capability de Codegen Semántico
# ============================================================

class CodegenSemantic:
    """Capability que traduce Intent IR → Código en lenguaje objetivo
    verificando compatibilidad semántica."""
    
    def __init__(self):
        self.mappings = PRIMITIVE_TO_LANG_OP
    
    def supports_language(self, language: str) -> bool:
        """¿Tiene mapeos para este lenguaje?"""
        return any(language in ops for ops in self.mappings.values())
    
    def supports_primitive(self, primitive: str, language: str) -> bool:
        """¿Esta primitiva tiene mapeo para este lenguaje?"""
        return primitive in self.mappings and language in self.mappings[primitive]
    
    def verify_semantic_match(self, primitive: str, language: str, intent_operands: dict) -> tuple[bool, float]:
        """Verifica que la primitiva tiene sentido semántico en el lenguaje objetivo.
        
        Returns: (compatible, confidence_score)
        """
        if not self.supports_primitive(primitive, language):
            return False, 0.0
        
        # Verificación básica: el mapeo existe
        mapping = self.mappings[primitive][language]
        
        # Verificar que los operandos requeridos están presentes
        template = mapping.get("template", "")
        # Extraer placeholders del template (simple heuristic)
        placeholders = set(re.findall(r'\{(\w+)\}', template))
        
        missing = placeholders - set(intent_operands.keys())
        if missing:
            return False, 0.5  # Faltan operandos
        
        if mapping.get("hook") or not mapping.get("verified", True):
            return False, 0.0
        return True, 1.0
    
    def generate(self, primitive: str, language: str, intent_operands: dict) -> CodegenResult:
        """Genera código para primitiva en lenguaje objetivo."""
        
        if not self.supports_primitive(primitive, language):
            raise ValueError(f"No mapping for {primitive} -> {language}")
        
        mapping = self.mappings[primitive][language]
        
        # Verificar compatibilidad
        compatible, score = self.verify_semantic_match(primitive, language, intent_operands)
        hook = bool(mapping.get("hook"))
        if not compatible and not (hook or mapping.get("allow_unverified")):
            raise ValueError(f"Semantic mismatch: {primitive} not compatible with {language} for operands {intent_operands}")
        
        # Generar código sustituyendo placeholders con quoting
        template = mapping.get("template")
        if not isinstance(template, str):
            raise ValueError(f"Mapping has no template for {primitive} -> {language}")
        code = template
        
        # Sustituir placeholders con quoting por lenguaje
        for key, value in intent_operands.items():
            quoted = quote_for_language(str(value), language)
            code = code.replace(f"{{{key}}}", quoted)
        
        # Agregar imports
        imports = mapping.get("imports", [])
        if imports:
            code = "\n".join(imports) + "\n\n" + code
        
        return CodegenResult(
            language=language,
            primitive=primitive,
            code=code,
            verified=bool(mapping.get("verified", not hook)),
            semantic_score=score,
        )
    
    def generate_from_program(self, program: Program, language: str) -> list[CodegenResult]:
        """Genera código para todo un Program (múltiples nodos).
        
        Recorre el árbol Program IR y genera código para cada nodo CALL.
        """
        results: list[CodegenResult] = []
        self._walk_program(program.root, language, results)
        return results
    
    def _walk_program(self, node, language: str, results: list[CodegenResult]) -> None:
        """Recorre nodos del Program IR y genera código para cada CALL."""
        if not hasattr(node, 'primitive'):
            return
        
        # Si es un nodo CALL, generar código
        if node.primitive == 'CALL':
            # La capability esta en args[0] como VALUE node
            cap_node = node.args[0] if node.args else None
            capability = cap_node.kwargs.get('raw', '') if cap_node else ''
            
            # Extraer primitiva del capability name
            # cap.fs.copy -> COPY, cap.process.run -> RUN
            capability_map = {
                'cap.fs.copy': 'COPY', 'cap.fs.move': 'MOVE',
                'cap.fs.delete': 'DELETE', 'cap.fs.read': 'READ',
                'cap.fs.write': 'WRITE', 'cap.fs.modify': 'CHANGE',
                'cap.process.run': 'RUN', 'cap.process.exec': 'EXECUTE',
                'cap.net.download': 'DOWNLOAD', 'cap.net.connect': 'CONNECT',
                'cap.build.compile': 'COMPILE', 'cap.build.test': 'TEST',
                'cap.crypto.sign': 'SIGN', 'cap.crypto.encrypt': 'ENCRYPT',
                'cap.crypto.decrypt': 'DECRYPT',
                'cap.archive.create': 'ARCHIVE', 'cap.archive.extract': 'EXTRACT',
            }
            primitive = capability_map.get(capability)
            if primitive:
                # Extraer operands del nodo (kwargs)
                operands = {}
                for k, v in node.kwargs.items():
                    if hasattr(v, 'kwargs'):
                        operands[k] = v.kwargs.get('raw', str(v))
                result = self.generate(primitive, language, operands)
                results.append(result)
        
        # Recursar en args y kwargs
        for arg in getattr(node, 'args', []):
            self._walk_program(arg, language, results)
        for val in getattr(node, 'kwargs', {}).values():
            if hasattr(val, 'args'):
                self._walk_program(val, language, results)
    
    
# ============================================================
# Entry points
# ============================================================

_codegen_semantic = None

def get_codegen_semantic() -> CodegenSemantic:
    global _codegen_semantic
    if _codegen_semantic is None:
        _codegen_semantic = CodegenSemantic()
    return _codegen_semantic


def generate_code(primitive: str, language: str, operands: dict) -> CodegenResult:
    """Genera código para primitiva en lenguaje."""
    return get_codegen_semantic().generate(primitive, language, operands)


def generate_from_program(program: Program, language: str) -> list[CodegenResult]:
    """Genera código para todo un Program IR en el lenguaje dado."""
    return get_codegen_semantic().generate_from_program(program, language)


def verify_codegen_compatibility(primitive: str, language: str, operands: dict) -> tuple[bool, float]:
    """Verifica compatibilidad semántica sin generar código."""
    return get_codegen_semantic().verify_semantic_match(primitive, language, operands)


def list_supported_languages() -> list[str]:
    """Lenguajes con al menos un mapeo."""
    langs: set[str] = set()
    for ops in PRIMITIVE_TO_LANG_OP.values():
        langs.update(ops.keys())
    return sorted(langs)


def list_primitives_for_language(language: str) -> list[str]:
    """Primitivas disponibles para un lenguaje."""
    return [p for p, ops in PRIMITIVE_TO_LANG_OP.items() if language in ops]
