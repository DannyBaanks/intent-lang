"""Download/ensure all WordNets used by tests. Called by CI."""
import sys

sys.path.insert(0, "src")
from intentlang import lexicon

for lang in ("es", "en", "zh", "ja", "ar", "fi", "he"):
    lexicon.ensure_installed(lang)
print("WordNets installed:", lexicon.supported_languages())