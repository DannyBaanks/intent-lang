import pytest

from intentlang import lexicon
from intentlang.resolve import resolve


@pytest.fixture(scope="module", autouse=True)
def _instalar():
    lexicon.ensure_installed("es")


def test_strict_es_byte_identico_entre_corridas():
    a = resolve("copia el archivo", "es", mode="strict").to_dict()
    b = resolve("copia el archivo", "es", mode="strict").to_dict()
    assert a == b
