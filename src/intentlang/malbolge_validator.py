"""Malbolge Evidence Validator: valida código Malbolge y adjunta evidence_sha256.

Cada ejecución Malbolge genera evidence con:
- evidence_sha256: hash del evidence completo
- bfs_iterations: iteraciones del BFS para encontrar el programa
- program_hash: hash del programa Malbolge generado
- execution_result: resultado de la ejecución
- verification: validación semántica contra intent original
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .codegen import generate_code
from .ir import Intent
from .lowering import lower_text_to_program
from .resolve import resolve


@dataclass(frozen=True, slots=True)
class MalbolgeEvidence:
    """Evidence completo de ejecución Malbolge."""
    # Identidad
    evidence_sha256: str              # sha256 del evidence completo
    program_sha256: str               # sha256 del programa Malbolge
    
    # Metadatos
    timestamp: float                  # Unix timestamp
    source_text: str                  # Texto original
    language: str                     # Código de idioma
    intent_primitive: str             # Primitiva del intent
    intent_status: str                # Status del intent
    
    # Generación
    malbolge_program: str             # Programa Malbolge generado
    bfs_iterations: int               # Iteraciones BFS (si aplica)
    generation_time_ms: float         # Tiempo de generación
    
    # Ejecución
    execution_result: dict            # Resultado de ejecución
    execution_time_ms: float          # Tiempo de ejecución
    execution_stdout: str             # Stdout de ejecución
    execution_stderr: str             # Stderr de ejecución
    execution_exit_code: int          # Exit code
    
    # Verificación
    semantic_verification: dict       # Verificación semántica vs intent
    semantic_score: float             # Score de verificación (0.0-1.0)
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @property
    def success(self) -> bool:
        return self.execution_exit_code == 0 and self.semantic_score > 0.5


class MalbolgeValidator:
    """Validador de programas Malbolge con evidence_sha256."""
    
    def __init__(self, meowbolge_path: str | None = None):
        self.meowbolge_path = meowbolge_path or self._find_meowbolge()
        self.malbolge_dir = Path.cwd() / ".malbolge_cache"
        self.malbolge_dir.mkdir(parents=True, exist_ok=True)
    
    def _find_meowbolge(self) -> str:
        """Encuentra el ejecutable meowbolge."""
        import shutil
        meow = shutil.which("meowbolge")
        if meow:
            return meow
        candidates = [
            Path.home() / ".cargo" / "bin" / "meowbolge.exe",
            Path.home() / ".cargo" / "bin" / "meowbolge",
        ]
        for c in candidates:
            if c.exists():
                return str(c)
        return "meowbolge"
    
    def _program_hash(self, program: str) -> str:
        return "sha256:" + hashlib.sha256(program.encode("utf-8")).hexdigest()
    
    def _evidence_sha256(self, evidence: dict) -> str:
        serialized = json.dumps(evidence, sort_keys=True, ensure_ascii=False)
        return "sha256:" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    
    def generate_and_validate(self, text: str, language: str = "es") -> dict:
        """Pipeline completo: texto -> intent -> malbolge -> ejecución -> evidence."""
        start_time = time.time()
        
        # 1. Resolve
        intent = resolve(text, language)
        
        # 2. Lowering
        _program_ir = lower_text_to_program(text, language)
        
        # 3. Codegen Malbolge - usa la primitiva real del intent
        operands = {}
        # Para COPY/MOVE: src = operand, dst = scope
        # Para otras: usa verb/operand según la primitiva
        if intent.primitive in ("COPY", "MOVE"):
            if intent.operand:
                operands['src'] = intent.operand.lemma
            if intent.scope:
                operands['dst'] = intent.scope.lemma
        else:
            if intent.verb:
                operands['src'] = intent.verb.lemma
            if intent.operand:
                operands['dst'] = intent.operand.lemma
        if intent.operand:
            operands['path'] = intent.operand.lemma
        if intent.verb:
            operands['cmd'] = intent.verb.lemma
        operands['content'] = 'test'
        
        codegen_start = time.time()
        primitive = intent.primitive or "UNKNOWN"
        codegen_result = generate_code(primitive, 'malbolge', operands)
        generation_time_ms = (time.time() - codegen_start) * 1000
        
        malbolge_program = codegen_result.code
        _program_sha = self._program_hash(malbolge_program)
        
        # 4. Ejecutar con meowbolge
        exec_start = time.time()
        exec_result = self._execute_malbolge(malbolge_program)
        exec_time_ms = (time.time() - exec_start) * 1000
        
        # Verificación semántica - usa valores reales
        semantic_verify = self._verify_semantic(codegen_result, intent)
        
        # Construir evidence con VALORES REALES
        evidence = {
            "evidence_sha256": "",  # se llena abajo
            "program_sha256": self._program_hash(malbolge_program),
            "timestamp": time.time(),
            "source_text": text,
            "language": language,
            "intent_primitive": intent.primitive,
            "intent_status": intent.status.value,
            "malbolge_program": malbolge_program,
            "bfs_iterations": 0,
            "generation_time_ms": generation_time_ms,
            "execution_result": {
                "exit_code": exec_result.get("exit_code", -1),
                "stdout": exec_result.get("stdout", ""),
                "stderr": exec_result.get("stderr", ""),
            },
            "execution_time_ms": exec_time_ms,
            "execution_stdout": exec_result.get("stdout", ""),
            "execution_stderr": exec_result.get("stderr", ""),
            "execution_exit_code": exec_result.get("exit_code", -1),
            "semantic_verification": {
                "verified": semantic_verify.get("verified", False),
                "method": semantic_verify.get("method", "none"),
                "expected_primitive": intent.primitive,
                "generated_primitive": semantic_verify.get("generated_primitive", "UNKNOWN"),
            },
            "semantic_score": semantic_verify.get("score", 0.0),
        }
        
        # Calcular evidence_sha256
        evidence_sha = "sha256:" + hashlib.sha256(
            json.dumps(evidence, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        evidence["evidence_sha256"] = evidence_sha
        
        total_time_ms = (time.time() - start_time) * 1000
        
        return {
            "evidence": evidence,
            "total_time_ms": total_time_ms,
            "success": evidence["execution_exit_code"] == 0 and evidence["semantic_score"] > 0.5,
        }
    
    def _execute_malbolge(self, program: str) -> dict:
        """Ejecuta programa Malbolge con meowbolge."""
        prog_file = self.malbolge_dir / "program.mal"
        prog_file.write_text(program, encoding="utf-8")
        
        try:
            result = subprocess.run(
                [self.meowbolge_path, "run", str(prog_file)],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
                cwd=self.malbolge_dir,
            )
            return {
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        except subprocess.TimeoutExpired:
            return {"exit_code": -1, "stdout": "", "stderr": "timeout"}
        except FileNotFoundError:
            return {"exit_code": -1, "stdout": "", "stderr": "meowbolge not found"}
        except Exception as e:
            return {"exit_code": -1, "stdout": "", "stderr": str(e)}
    
    def _verify_semantic(self, codegen_result, intent: Intent) -> dict:
        """Verifica que el código generado coincide semánticamente con el intent."""
        # Verificación básica: la primitiva del codegen debe coincidir con la del intent
        if not codegen_result or not codegen_result.code:
            return {"verified": False, "method": "codegen_empty", "score": 0.0}
        
        # Extraer primitiva del código generado (buscar MALBOLGE_*)
        import re
        generated_primitive = "UNKNOWN"
        match = re.search(r'\(MALBOLGE_(\w+)', codegen_result.code)
        if match:
            generated_primitive = match.group(1)
        
        verified = (generated_primitive == intent.primitive)
        return {
            "verified": verified,
            "method": "codegen_primitive_match",
            "expected_primitive": intent.primitive,
            "generated_primitive": generated_primitive,
            "score": 1.0 if verified else 0.0,
        }


# Instancia global
_global_validator: MalbolgeValidator | None = None


def get_malbolge_validator(meowbolge_path: str | None = None) -> MalbolgeValidator:
    global _global_validator
    if _global_validator is None:
        _global_validator = MalbolgeValidator(meowbolge_path)
    return _global_validator


def validate_malbolge_pipeline(text: str, language: str = "es") -> dict:
    """Pipeline completo de validación Malbolge."""
    validator = get_malbolge_validator()
    return validator.generate_and_validate(text, language)
