"""CLI del engine-lang: install, verify, list, validate."""

from __future__ import annotations

import argparse
import sys

from engine_lang.contract import validate_and_print
from engine_lang.installer import Installer
from engine_lang.registry import registry
from engine_lang.verifier import overall_exit_code, print_report, verify_all, verify_language


def cmd_list(args) -> int:
    reg = registry()
    print("Installed languages:")
    for code in reg.supported_languages:
        pack = reg.get_pack(code)
        status = "OK" if reg.is_language_installed(code) else "MISSING"
        name_ascii = pack.name.encode('ascii', 'replace').decode('ascii')
        print(f"  {code:3} ({name_ascii:12}) [{status}] wordnet={pack.wordnet_package} tok={pack.tokenizer_strategy}")
    return 0


def cmd_verify(args) -> int:
    if args.code:
        results = {args.code: verify_language(args.code)}
    else:
        results = verify_all()
    print_report(results)
    return overall_exit_code(results)


def cmd_validate(args) -> int:
    ok = validate_and_print()
    return 0 if ok else 1


def cmd_install(args) -> int:
    inst = Installer()
    result = inst.install(args.code, force=args.force)
    if result["success"]:
        print(f"[OK] Installed {args.code}")
    else:
        print(f"[FAIL] {result['error']}")
        return 1
    return 0


def cmd_uninstall(args) -> int:
    inst = Installer()
    result = inst.uninstall(args.code)
    if result["success"]:
        print(f"[OK] Uninstalled {args.code}")
    else:
        print(f"[FAIL] {result['error']}")
        return 1
    return 0


def cmd_remote(args) -> int:
    inst = Installer()
    print("Remote registry:")
    for code, url in inst.list_remote().items():
        status = "installed" if code in inst.list_local() else "available"
        print(f"  {code:3} [{status}] {url}")
    return 0


def cmd_ensure_wordnet(args) -> int:
    inst = Installer()
    result = inst.ensure_wordnet(args.code)
    if result["success"]:
        print(f"[OK] WordNet {result['package']} downloaded")
    else:
        print(f"[FAIL] {result['error']}")
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="engine-lang", description="intent-lang language pack manager")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="list installed languages")

    v = sub.add_parser("verify", help="verify language pack(s)")
    v.add_argument("code", nargs="?", help="language code (default: all)")

    sub.add_parser("validate", help="validate all YAMLs against JSON Schema")

    i = sub.add_parser("install", help="install language pack from remote registry")
    i.add_argument("code", help="language code")
    i.add_argument("--force", action="store_true", help="reinstall if exists")

    u = sub.add_parser("uninstall", help="uninstall language pack")
    u.add_argument("code", help="language code")

    sub.add_parser("remote", help="list remote registry")

    w = sub.add_parser("ensure-wordnet", help="download wordnet if missing")
    w.add_argument("code", help="language code")

    args = parser.parse_args()

    handlers = {
        "list": cmd_list,
        "verify": cmd_verify,
        "validate": cmd_validate,
        "install": cmd_install,
        "uninstall": cmd_uninstall,
        "remote": cmd_remote,
        "ensure-wordnet": cmd_ensure_wordnet,
    }

    return handlers[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())