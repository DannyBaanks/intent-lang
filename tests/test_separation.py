"""La unica metrica que puede reprobar el build.

Convergencia sola es una metrica trampa: un sistema que mapea todo a ADD
converge perfecto y no sirve. El fallo peligroso es que dos intenciones
DISTINTAS colapsen a la misma representacion.
"""
import json
from collections import defaultdict
from pathlib import Path

import pytest
from intentlang import lexicon
from intentlang.ir import Status
from intentlang.resolve import resolve

CORPUS = Path(__file__).resolve().parents[1] / "corpus" / "seed.jsonl"


def cargar():
    return [json.loads(l) for l in CORPUS.read_text(encoding="utf-8").splitlines() if l.strip()]


@pytest.fixture(scope="module", autouse=True)
def _instalar():
    for lang in ("es", "en", "zh"):
        lexicon.ensure_installed(lang)


def test_separacion_es_perfecta():
    """INVARIANTE: dos etiquetas distintas nunca comparten key."""
    por_key = defaultdict(set)
    for caso in cargar():
        intent = resolve(caso["text"], caso["lang"])
        if intent.status is Status.RESOLVED:
            por_key[intent.key()].add(caso["label"])

    colisiones = {k: v for k, v in por_key.items() if len(v) > 1}
    assert not colisiones, f"colapso semantico entre intenciones distintas: {colisiones}"


def test_convergencia_se_reporta_no_reprueba(capsys):
    """Se mide y se informa. NO hace fallar el build."""
    por_label = defaultdict(list)
    for caso in cargar():
        por_label[caso["label"]].append(resolve(caso["text"], caso["lang"]))

    total = convergen = 0
    for label, intents in por_label.items():
        resueltos = [i for i in intents if i.status is Status.RESOLVED]
        if len(resueltos) < 2:
            continue
        total += 1
        if len({i.key() for i in resueltos}) == 1:
            convergen += 1

    pct = 100 * convergen / total if total else 0
    with capsys.disabled():
        print(f"\n  convergencia: {convergen}/{total} grupos ({pct:.0f}%)")
