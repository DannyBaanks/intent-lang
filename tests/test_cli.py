import json

import pytest

from intentlang import lexicon
from intentlang.cli import record_judgment


@pytest.fixture(scope="module", autouse=True)
def _instalar():
    lexicon.ensure_installed("es")


def test_el_juicio_humano_se_vuelve_corpus(tmp_path):
    """Cada 'si/no' humano se convierte en caso etiquetado que despues corre solo."""
    destino = tmp_path / "corpus.jsonl"
    record_judgment("copia el archivo", "es", "si", destino)
    record_judgment("borra el archivo", "es", "no", destino)

    lineas = [json.loads(line) for line in destino.read_text(encoding="utf-8").splitlines()]
    assert len(lineas) == 2
    assert lineas[0]["verdict"] == "si"
    assert lineas[0]["text"] == "copia el archivo"
    assert "key" in lineas[0]


def test_es_append_only(tmp_path):
    destino = tmp_path / "corpus.jsonl"
    record_judgment("copia el archivo", "es", "si", destino)
    record_judgment("copia el archivo", "es", "si", destino)
    assert len(destino.read_text(encoding="utf-8").splitlines()) == 2
