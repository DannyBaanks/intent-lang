"""Verificador de language packs: valida YAML contra contrato y prueba wordnet."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from engine_lang.registry import registry

_CONTRACT = Path(__file__).resolve().parent / "contracts" / "language.v1.json"


def _load_contract() -> dict:
    return json.loads(_CONTRACT.read_text(encoding="utf-8"))


def validate_yaml(yaml_path: Path) -> list[str]:
    """Valida un YAML contra el contrato JSON Schema. Devuelve lista de errores."""
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    errors = []
    try:
        jsonschema.validate(data, _load_contract())
    except jsonschema.ValidationError as e:
        errors.append(f"{yaml_path.name}: {e.message}")
    return errors


def verify_language(code: str) -> dict[str, Any]:
    """Verifica un language pack completo. Devuelve dict con estado."""
    reg = registry()
    result = {
        "code": code,
        "yaml_exists": reg.has_language(code),
        "wordnet_available": False,
        "tokenizer_works": False,
        "corpus_resolves": 0,
        "corpus_correct": 0,
        "corpus_total": 0,
        "errors": [],
    }

    if not result["yaml_exists"]:
        result["errors"].append(f"Language pack '{code}' not found in registry")
        return result

    pack = reg.get_pack(code)

    # Verificar wordnet
    import wn
    try:
        wn.Wordnet(pack.wordnet_package)
        result["wordnet_available"] = True
    except wn.Error as e:
        result["errors"].append(f"WordNet unavailable: {e}")

    # Verificar tokenizer
    try:
        from intentlang.normalize import tokens
        test_text = pack.corpus[0]["text"] if pack.corpus else "test"
        tokens(test_text, code)
        result["tokenizer_works"] = True
    except Exception as e:
        result["errors"].append(f"Tokenizer failed: {e}")

    # Verificar corpus semánticamente (solo si wordnet disponible)
    if result["wordnet_available"]:
        from intentlang.ir import Status
        from intentlang.resolve import resolve
        for entry in pack.corpus:
            intent = resolve(entry["text"], code)
            result["corpus_total"] += 1
            expected = entry.get("label")
            
            # Convertir label legacy string a formato semántico
            expected_key = None
            if expected and isinstance(expected, list) and len(expected) >= 2:
                expected_key = (expected[0], expected[1], None)
            elif expected and isinstance(expected, str):
                # Legacy format "PRIMITIVE/operand" → convertir
                parts = expected.split("/", 1)
                if len(parts) == 2:
                    # Intentar encontrar el ILI por el nombre del operando (heurístico)
                    expected_key = (parts[0], None, None)  # Partial match
            
            if intent.status is not Status.RESOLVED:
                result["errors"].append(
                    f"Corpus NOT RESOLVED: '{entry['text']}' -> {intent.status.value}"
                    + (f" (expected {expected_key})" if expected_key else "")
                )
            else:
                result["corpus_resolves"] += 1
                if expected_key:
                    if intent.key() == expected_key:
                        result["corpus_correct"] += 1
                    else:
                        result["errors"].append(
                            f"Semantic mismatch: '{entry['text']}' -> key {intent.key()} != expected {expected_key}"
                        )

    return result


def verify_all() -> dict[str, Any]:
    """Verifica todos los language packs instalados."""
    reg = registry()
    results = {}
    for code in reg.supported_languages:
        results[code] = verify_language(code)
    return results


def print_report(results: dict[str, Any]) -> None:
    """Imprime reporte legible (ASCII-safe)."""
    print("\n=== LANGUAGE PACK VERIFICATION REPORT ===")
    for code, r in sorted(results.items()):
        status = "[OK]" if not r["errors"] else "[FAIL]"
        print(f"\n{code.upper()} {status}")
        print(f"  YAML:        {'found' if r['yaml_exists'] else 'MISSING'}")
        print(f"  WordNet:     {'available' if r['wordnet_available'] else 'MISSING'}")
        print(f"  Tokenizer:   {'works' if r['tokenizer_works'] else 'FAILED'}")
        if r["wordnet_available"]:
            print(f"  Corpus:      {r['corpus_resolves']}/{r['corpus_total']} resolved, {r['corpus_correct']}/{r['corpus_total']} semantically correct")
        for err in r["errors"]:
            # Make ASCII-safe
            safe_err = err.encode('ascii', 'replace').decode('ascii')
            print(f"  ERROR:       {safe_err}")

    total = len(results)
    passed = sum(1 for r in results.values() if not r["errors"])
    print(f"\n=== SUMMARY: {passed}/{total} languages fully verified ===")


def overall_exit_code(results: dict[str, Any]) -> int:
    """Devuelve 0 si todo OK, 1 si hay cualquier FAIL."""
    for r in results.values():
        if r["errors"]:
            return 1
    return 0


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        code = sys.argv[1]
        r = verify_language(code)
        print_report({code: r})
        sys.exit(overall_exit_code({code: r}))
    else:
        results = verify_all()
        print_report(results)
        sys.exit(overall_exit_code(results))