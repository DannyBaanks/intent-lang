"""Instalador de language packs: descarga, valida y registra."""

from __future__ import annotations

import urllib.request
from pathlib import Path
from typing import Any

from engine_lang.contract import validate_yaml_file
from engine_lang.registry import get_remote_registry
from engine_lang.registry import reload as reload_registry
from engine_lang.verifier import verify_language


class Installer:
    """Gestiona instalación de language packs desde registro remoto."""

    def __init__(self):
        self.local_langs = Path(__file__).resolve().parent / "languages"
        self.local_langs.mkdir(parents=True, exist_ok=True)

    def list_remote(self) -> dict[str, str]:
        """Lista language packs disponibles en el registro remoto."""
        return get_remote_registry()

    def list_local(self) -> list[str]:
        """Lista language packs instalados localmente."""
        return sorted(f.stem for f in self.local_langs.glob("*.yaml"))

    def install(self, code: str, force: bool = False) -> dict[str, Any]:
        """Instala un language pack: descarga -> valida -> verifica wordnet."""
        code = code.lower()
        remote = self.list_remote()

        if code not in remote:
            return {"success": False, "error": f"Language '{code}' not in remote registry"}

        local_path = self.local_langs / f"{code}.yaml"
        if local_path.exists() and not force:
            return {"success": False, "error": "Already installed (use --force to reinstall)"}

        # Descargar
        try:
            urllib.request.urlretrieve(remote[code], local_path)
        except Exception as e:
            return {"success": False, "error": f"Download failed: {e}"}

        # Validar contrato
        errors = validate_yaml_file(local_path)
        if errors:
            local_path.unlink(missing_ok=True)
            return {"success": False, "error": f"Contract validation failed: {errors}"}

        # Recargar registry
        reload_registry()

        # Verificar wordnet
        result = verify_language(code)

        if not result["wordnet_available"]:
            local_path.unlink(missing_ok=True)
            reload_registry()
            return {
                "success": False,
                "error": f"WordNet not available for '{code}'. Cannot install without wordnet.",
                "verification": result,
            }

        return {"success": True, "code": code, "verification": result}

    def uninstall(self, code: str) -> dict[str, Any]:
        """Desinstala un language pack local."""
        code = code.lower()
        local_path = self.local_langs / f"{code}.yaml"
        if not local_path.exists():
            return {"success": False, "error": f"Language '{code}' not installed"}
        local_path.unlink()
        reload_registry()
        return {"success": True, "code": code}

    def ensure_wordnet(self, code: str) -> dict[str, Any]:
        """Descarga el wordnet si falta (usa wn.download)."""
        from engine_lang.registry import registry
        reg = registry()
        if not reg.has_language(code):
            return {"success": False, "error": f"Language '{code}' not in registry"}

        pack = reg.get_pack(code)
        import wn
        try:
            wn.download(pack.wordnet_package)
            return {"success": True, "package": pack.wordnet_package}
        except Exception as e:
            return {"success": False, "error": str(e)}


if __name__ == "__main__":
    import sys
    inst = Installer()
    if len(sys.argv) < 2:
        print("Usage: installer.py <install|uninstall|list|ensure-wordnet> [code]")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "list":
        print("Remote:", inst.list_remote())
        print("Local:", inst.list_local())
    elif cmd == "install" and len(sys.argv) > 2:
        print(inst.install(sys.argv[2]))
    elif cmd == "uninstall" and len(sys.argv) > 2:
        print(inst.uninstall(sys.argv[2]))
    elif cmd == "ensure-wordnet" and len(sys.argv) > 2:
        print(inst.ensure_wordnet(sys.argv[2]))
    else:
        print("Invalid command")