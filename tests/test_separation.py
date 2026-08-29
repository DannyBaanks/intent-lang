"""La unica metrica que puede reprobar el build.

Convergencia sola es una metrica trampa: un sistema que mapea todo a ADD
converge perfecto y no sirve. El fallo peligroso es que dos intenciones
DISTINTAS colapsen a la misma representacion.
"""
import json
from collections import defaultdict
from pathlib import Path

import pytest

from engine_lang.registry import registry
from intentlang import lexicon
from intentlang.ir import Status
from intentlang.resolve import resolve

LANGS = registry().supported_languages
LANGS_WN = registry().languages_with_wordnet

CORPUS = Path(__file__).resolve().parents[1] / "corpus" / "seed.jsonl"


def cargar():
    return [json.loads(line) for line in CORPUS.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.fixture(scope="module", autouse=True)
def _instalar():
    for lang in LANGS_WN:
        lexicon.ensure_installed(lang)


def test_separacion_es_perfecta():
    """INVARIANTE: dos etiquetas distintas nunca comparten key.

    También valida que el pipeline no regresó totalmente (al menos 2 casos
    deben resolver a RESOLVED; con 9 casos en el corpus, 2+ indica que
    el resolve() está funcionando en lo básico).
    """
    por_key = defaultdict(set)
    resueltos = 0
    for caso in cargar():
        intent = resolve(caso["text"], caso["lang"])
        if intent.status is Status.RESOLVED:
            por_key[intent.key()].add(caso["label"])
            resueltos += 1

    # Piso de cobertura: con 9 casos en el corpus, al menos 2 deben resolver
    assert resueltos >= 2, (
        f"regresion del pipeline: solo {resueltos} de 9 casos llegaron a RESOLVED. "
        f"El resolve() parece estar fallando totalmente."
    )

    colisiones = {k: v for k, v in por_key.items() if len(v) > 1}
    assert not colisiones, f"colapso semantico entre intenciones distintas: {colisiones}"


def test_convergencia_se_reporta_no_reprueba(capsys):
    """Se mide y se informa. NO hace fallar el build."""
    por_label = defaultdict(list)
    for caso in cargar():
        por_label[caso["label"]].append(resolve(caso["text"], caso["lang"]))

    total = convergen = 0
    for intents in por_label.values():
        resueltos = [i for i in intents if i.status is Status.RESOLVED]
        if len(resueltos) < 2:
            continue
        total += 1
        if len({i.key() for i in resueltos}) == 1:
            convergen += 1

    pct = 100 * convergen / total if total else 0
    with capsys.disabled():
        print(f"\n  convergencia: {convergen}/{total} grupos ({pct:.0f}%)")
