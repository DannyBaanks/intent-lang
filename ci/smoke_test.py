"""Smoke test: resolve -> lower -> codegen + capability binding end-to-end.

Checks that the pipeline really works (not an assertion that accepts
failure). Called by CI.
"""
import sys

sys.path.insert(0, "src")

from intentlang import lower_text_to_program, resolve
from intentlang.capabilities import CAPABILITY_REGISTRY
from intentlang.codegen import generate_from_program
from intentlang.lowering import PRIMITIVE_TO_CAPABILITY

# 1. Resolve da RESOLVED y detecta scope
intent = resolve("copia el archivo al directorio", "es")
assert intent.status.value == "RESOLVED", f"Expected RESOLVED, got {intent.status.value}"
assert intent.primitive in ("COPY", "MOVE"), "Expected COPY/MOVE"
assert intent.scope is not None, "Scope (destination) should be detected"
assert intent.scope.lemma == "directorio", "dst should be directorio"

# 2. Lower produce Program con src/dst correctos
prog = lower_text_to_program("copia el archivo al directorio", "es")
kw = prog.root.kwargs
assert kw["src"].kwargs.get("raw") == "archivo", "src should be archivo"
assert kw["dst"].kwargs.get("raw") == "directorio", "dst should be directorio"

# 3. Toda primitiva -> capability registrada
for prim, cap in PRIMITIVE_TO_CAPABILITY.items():
    assert cap in CAPABILITY_REGISTRY, f"primitive {prim} -> {cap} not registered"

# 4. Codegen produce codigo desde Program IR
results = generate_from_program(prog, "python")
assert len(results) >= 1, "codegen should produce at least 1 target"
assert all(r.code for r in results), "each target should have code"

print("Smoke test passed: resolve + lower + codegen + capability binding end-to-end")