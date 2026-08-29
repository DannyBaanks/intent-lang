"""Validador de contratos: YAML vs JSON Schema."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import yaml

_CONTRACT = Path(__file__).resolve().parent / "contracts" / "language.v1.json"


def _load_contract() -> dict:
    return json.loads(_CONTRACT.read_text(encoding="utf-8"))


def validate_yaml_file(yaml_path: Path) -> list[str]:
    """Valida un archivo YAML contra el contrato. Devuelve lista de errores."""
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    errors = []
    try:
        jsonschema.validate(data, _load_contract())
    except jsonschema.ValidationError as e:
        errors.append(f"{yaml_path.name}: {e.message} at {'.'.join(str(p) for p in e.path)}")
    return errors


def validate_all() -> dict[str, list[str]]:
    """Valida todos los YAMLs en languages/. Devuelve dict code -> errores."""
    langs_dir = Path(__file__).resolve().parent / "languages"
    results = {}
    for yaml_file in sorted(langs_dir.glob("*.yaml")):
        code = yaml_file.stem
        results[code] = validate_yaml_file(yaml_file)
    return results


def validate_and_print() -> bool:
    """Valida todo e imprime reporte. Devuelve True si todo OK."""
    results = validate_all()
    all_ok = True
    for code, errors in sorted(results.items()):
        if errors:
            print(f"[FAIL] {code}")
            for err in errors:
                print(f"  {err}")
            all_ok = False
        else:
            print(f"[OK]   {code}")
    return all_ok


if __name__ == "__main__":
    import sys
    ok = validate_and_print()
    sys.exit(0 if ok else 1)