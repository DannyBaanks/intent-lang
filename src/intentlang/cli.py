"""Entrada de linea de comandos y arnes de juicio humano.

El arnes es la barra de exito del proyecto: muestra lo que el sistema entendio
y guarda el veredicto humano. Cada veredicto se vuelve un caso etiquetado, asi
que la metrica humana arranca el corpus que despues corre solo como regresion.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .relex import round_trip
from .resolve import resolve

CORPUS = Path(__file__).resolve().parents[2] / "corpus" / "seed.jsonl"


def record_judgment(text: str, lang: str, verdict: str,
                    path: Path = CORPUS) -> None:
    """Append-only. El corpus es bitacora, nunca se reescribe."""
    intent = resolve(text, lang)
    registro = {
        "text": text, "lang": lang, "verdict": verdict,
        "key": list(intent.key()), "status": intent.status.value,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(registro, ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None) -> int:
    # La consola de Windows suele quedar en cp1252: sin esto, el es/zh que el
    # arnes tiene que MOSTRAR se corrompe antes de llegar al humano que juzga.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(prog="intentlang")
    sub = parser.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("resolve", help="resolver texto a IR")
    r.add_argument("text")
    r.add_argument("--lang", required=True, choices=["es", "en", "zh"])
    r.add_argument("--mode", default="strict", choices=["strict", "assisted"])

    j = sub.add_parser("judge", help="arnes de juicio humano")
    j.add_argument("text")
    j.add_argument("--lang", required=True, choices=["es", "en", "zh"])

    args = parser.parse_args(argv)
    intent = resolve(args.text, args.lang, getattr(args, "mode", "strict"))

    if args.cmd == "resolve":
        print(json.dumps(intent.to_dict(), ensure_ascii=False, indent=2))
        return 0

    print(round_trip(intent, args.lang))
    veredicto = input("[si / no / ambiguo] > ").strip().lower()
    record_judgment(args.text, args.lang, veredicto)
    print(f"anotado: {veredicto}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
