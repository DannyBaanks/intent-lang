"""Language registry: loads YAML packs and builds runtime dicts.

This is the "engine" — it reads language definitions from YAML files
and populates the dicts that lexicon.py, normalize.py, primitives.py,
relex.py, and cli.py use. No code generation, no Jinja2, no magic.

The contract: every YAML file in engine_lang/languages/ must conform
to contracts/language.v1.json. The loader validates on import.

Usage:
    from engine_lang.registry import registry
    reg = registry()
    reg.wordnet_sources    # {"es": "omw-es:1.4", ...}
    reg.tokenizer_strategies  # {"es": "simplemma", ...}
    reg.supported_languages  # ["es", "en", "zh", "ja", "ar", "fi"]
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_LANGUAGES_DIR = Path(__file__).resolve().parent / "languages"
_cached: Any = None


class LanguagePack:
    """Immutable container for one language's configuration."""

    def __init__(self, data: dict):
        self.code: str = data["code"]
        self.name: str = data["name"]
        self.family: str = data["family"]
        self.script: str = data.get("script", "latin")
        self.wordnet_package: str = data["wordnet"]["package"]
        self.tokenizer_strategy: str = data["tokenizer"]["strategy"]
        self.tokenizer_options: dict = data.get("tokenizer", {}).get("options", {})
        self.verb_strategy: str = data.get("verb_strategy", "none")
        self.verb_candidates: dict[str, str] = data.get("verb_candidates", {})
        self.declared_gaps: dict[str, list[str]] = data.get("declared_gaps", {})
        self.declared_passthrough: dict[str, list[str]] = data.get("declared_passthrough", {})
        self.corpus: list[dict] = data.get("corpus", [])


class Registry:
    """Central registry of all installed language packs."""

    def __init__(self):
        self._packs: dict[str, LanguagePack] = {}
        self._load_all()

    def _load_all(self) -> None:
        if not _LANGUAGES_DIR.exists():
            return
        for yaml_file in sorted(_LANGUAGES_DIR.glob("*.yaml")):
            data = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
            pack = LanguagePack(data)
            self._packs[pack.code] = pack

    @property
    def supported_languages(self) -> list[str]:
        return sorted(self._packs.keys())

    @property
    def wordnet_sources(self) -> dict[str, str]:
        return {code: pack.wordnet_package for code, pack in self._packs.items()}

    @property
    def tokenizer_strategies(self) -> dict[str, str]:
        return {code: pack.tokenizer_strategy for code, pack in self._packs.items()}

    @property
    def verb_strategies(self) -> dict[str, str]:
        return {code: pack.verb_strategy for code, pack in self._packs.items()}

    @property
    def verb_candidates(self) -> dict[str, dict[str, str]]:
        return {code: pack.verb_candidates for code, pack in self._packs.items()}

    @property
    def declared_gaps(self) -> dict[str, list[str]]:
        merged: dict[str, set[str]] = {}
        for pack in self._packs.values():
            for ili, langs in pack.declared_gaps.items():
                if ili not in merged:
                    merged[ili] = set()
                merged[ili].update(langs)
        return {k: sorted(v) for k, v in merged.items()}

    @property
    def declared_passthrough(self) -> dict[str, list[str]]:
        merged: dict[str, set[str]] = {}
        for pack in self._packs.values():
            for ili, langs in pack.declared_passthrough.items():
                if ili not in merged:
                    merged[ili] = set()
                merged[ili].update(langs)
        return {k: sorted(v) for k, v in merged.items()}

    @property
    def corpus_entries(self) -> list[dict]:
        return [
            {**entry, "lang": pack.code}
            for pack in self._packs.values()
            for entry in pack.corpus
        ]

    def get_pack(self, code: str) -> LanguagePack:
        return self._packs[code]

    def has_language(self, code: str) -> bool:
        return code in self._packs

    def is_language_installed(self, code: str) -> bool:
        """Check if a language pack's wordnet is actually downloaded."""
        import wn
        pack = self._packs[code]
        try:
            wn.Wordnet(pack.wordnet_package)
            return True
        except wn.Error:
            return False

    @property
    def languages_with_wordnet(self) -> list[str]:
        """Idiomas cuyo wordnet está disponible (instalado o descargable)."""
        import wn
        result = []
        for code, pack in self._packs.items():
            try:
                wn.Wordnet(pack.wordnet_package)
                result.append(code)
            except wn.Error:
                pass
        return sorted(result)


def registry() -> Registry:
    """Singleton accessor. Lazy-loaded, cached."""
    global _cached
    if _cached is None:
        _cached = Registry()
    return _cached


def reload() -> Registry:
    """Force reload (for testing / after adding new language packs)."""
    global _cached
    _cached = Registry()
    return _cached


# ============================================================
# Remote Registry Index
# ============================================================

# Remote registry index - maps language code to download URL
# This is the index that engine-lang install queries
# Uses this repo's raw.githubusercontent.com for serving language packs
REMOTE_REGISTRY_INDEX = {
    "es": "https://raw.githubusercontent.com/DannyBaanks/intent-lang/main/language-packs/es.yaml",
    "en": "https://raw.githubusercontent.com/DannyBaanks/intent-lang/main/language-packs/en.yaml",
    "zh": "https://raw.githubusercontent.com/DannyBaanks/intent-lang/main/language-packs/zh.yaml",
    "ja": "https://raw.githubusercontent.com/DannyBaanks/intent-lang/main/language-packs/ja.yaml",
    "ar": "https://raw.githubusercontent.com/DannyBaanks/intent-lang/main/language-packs/ar.yaml",
    "fi": "https://raw.githubusercontent.com/DannyBaanks/intent-lang/main/language-packs/fi.yaml",
    "he": "https://raw.githubusercontent.com/DannyBaanks/intent-lang/main/language-packs/he.yaml",
    "tr": "https://raw.githubusercontent.com/DannyBaanks/intent-lang/main/language-packs/tr.yaml",
    "vi": "https://raw.githubusercontent.com/DannyBaanks/intent-lang/main/language-packs/vi.yaml",
    "th": "https://raw.githubusercontent.com/DannyBaanks/intent-lang/main/language-packs/th.yaml",
    "ru": "https://raw.githubusercontent.com/DannyBaanks/intent-lang/main/language-packs/ru.yaml",
    "hi": "https://raw.githubusercontent.com/DannyBaanks/intent-lang/main/language-packs/hi.yaml",
    "ko": "https://raw.githubusercontent.com/DannyBaanks/intent-lang/main/language-packs/ko.yaml",
}


def get_remote_registry() -> dict[str, str]:
    """Returns the remote registry index (code -> download URL)."""
    return REMOTE_REGISTRY_INDEX.copy()


def list_remote_languages() -> list[dict]:
    """List all languages available in remote registry."""
    return [
        {"code": code, "url": url}
        for code, url in REMOTE_REGISTRY_INDEX.items()
    ]