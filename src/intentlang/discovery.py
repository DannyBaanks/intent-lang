"""Discovery Engine: motor de descubrimiento de primitives + capabilities.

Estilo Autobolge: no 'sabe' la respuesta; genera candidatos y deja
que la ejecución decida. Modelo propone, evidencia decide.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .capabilities import execute_capability, get_contract
from .lexicon import senses
from .primitives import primitive_for


@dataclass(frozen=True, slots=True)
class Candidate:
    """Candidato a primitiva + capability."""
    primitive: str
    capability: str          # ej: "cap.ffmpeg.render"
    contract: dict           # {input_schema, output_schema, preconditions, postconditions}
    confidence: float        # 0.0 - 1.0
    evidence: dict = field(default_factory=dict)  # resultados de verificacion


class DiscoveryEngine:
    """Genera candidatos para UNKNOWN, los prueba, registra los que pasan."""
    
    def __init__(self):
        self.candidates: list[Candidate] = []
        self.registered: dict[str, Candidate] = {}  # primitive -> Candidate
        self.test_cases: dict[str, list[dict]] = {}  # primitive -> test cases
    
    def enumerate_candidates(self, surface: str, lang: str) -> list[Candidate]:
        """De surface + lang -> lista de candidatos primitiva+capability.
        
        Pipeline:
        1. Tokeniza y busca verbos en el lexico (con verb_candidates para reconstruccion)
        2. Para cada verbo, busca primitivas asociadas
        3. Para cada primitiva, busca capabilities que la implementen
        4. Devuelve candidatos ordenados por confianza
        """
        candidates = []
        
        # 1. Tokenizar y buscar verbos (con reconstruccion de imperativos)
        from .normalize import tokens, verb_candidates
        lemmas = tokens(surface, lang)
        
        for lemma in lemmas:
            # Usar verb_candidates para reconstruir imperativos
            for candidate_lemma in verb_candidates(lemma, lang):
                # Buscar verbos en el lexico
                verb_senses = senses(candidate_lemma, lang, pos="v")
                for ili in verb_senses:
                    prim = primitive_for(ili)
                    if prim:
                        # 2. Para cada primitiva, buscar capabilities
                        for cap_name, contract in _find_capabilities_for_primitive(prim):
                            conf = _estimate_confidence(lemma, prim, contract)
                            candidates.append(Candidate(
                                primitive=prim,
                                capability=cap_name,
                                contract={
                                    "input_schema": contract.input_schema,
                                    "output_schema": contract.output_schema,
                                    "preconditions": len(contract.preconditions),
                                    "postconditions": len(contract.postconditions),
                                    "side_effects": contract.side_effects,
                                },
                                confidence=conf,
                            ))
        
        # Ordenar por confianza descendente
        candidates.sort(key=lambda c: c.confidence, reverse=True)
        return candidates
    
    def verify_candidate(self, candidate: Candidate, test_cases: list[dict]) -> bool:
        """Ejecuta test cases contra la capability. True si pasa todos."""
        for tc in test_cases:
            try:
                inputs = tc.get("inputs", {})
                expected = tc.get("expected", {})
                
                result = execute_capability(candidate.capability, inputs)
                
                # Validar contra expected
                for key, exp_val in expected.items():
                    if key not in result or result[key] != exp_val:
                        return False
                        
            except Exception:
                return False
        return True
    
    def register_primitive(self, candidate: Candidate, test_cases: list[dict]) -> bool:
        """Si verificación pasa, registra como nueva primitiva."""
        if self.verify_candidate(candidate, test_cases):
            self.registered[candidate.primitive] = candidate
            self.test_cases[candidate.primitive] = test_cases
            # Actualizar concept_map.json, PRIMITIVES, etc. (TODO: implementar)
            return True
        return False
    
    def discover_and_register(self, surface: str, lang: str, 
                              test_cases: list[dict]) -> Candidate | None:
        """Pipeline completo: surface -> candidatos -> verificar -> registrar."""
        for cand in self.enumerate_candidates(surface, lang):
            if self.verify_candidate(cand, test_cases):
                self.register_primitive(cand, test_cases)
                return cand
        return None
    
    def get_registered(self) -> dict[str, Candidate]:
        return self.registered.copy()


def _find_capabilities_for_primitive(primitive: str) -> list[tuple[str, Any]]:
    """Busca capabilities que implementen una primitiva."""
    # Mapeo primitiva -> capability names
    prim_to_caps = {
        "COPY": ["cap.fs.copy"],
        "MOVE": ["cap.fs.move"],
        "REMOVE": ["cap.fs.delete"],
        "DOWNLOAD": ["cap.net.download"],
        "COMPILE": ["cap.build.compile"],
        "RENDER": ["cap.media.render"],
        "SIGN": ["cap.crypto.sign"],
        "WRITE": ["cap.fs.write"],
        "READ": ["cap.fs.read"],
        "DELETE": ["cap.fs.delete"],
        "EXECUTE": ["cap.process.run"],
        "RUN": ["cap.process.run"],
        "QUERY": ["cap.query.exec"],
        "CONNECT": ["cap.net.connect"],
    }
    
    caps = prim_to_caps.get(primitive, [])
    result = []
    for cap_name in caps:
        contract = get_contract(cap_name)
        if contract:
            result.append((cap_name, contract))
    return result


def _estimate_confidence(lemma: str, primitive: str, contract: Any) -> float:
    """Estima confianza del candidato basada en heurísticas."""
    base = 0.5
    # Boost si el lema coincide con verbo comun de la primitiva
    verb_hints = {
        "COPY": {"copy", "copiar", "複製", "コピー", "نسخ"},
        "MOVE": {"move", "mover", "移動", "動かす", "نقل"},
        "REMOVE": {"delete", "remove", "borrar", "eliminar", "削除", "削る", "حذف"},
        "DOWNLOAD": {"download", "descargar", "ダウンロード", "تنزيل"},
        "COMPILE": {"compile", "compilar", "コンパイル", "تجميع"},
        "RENDER": {"render", "renderizar", "レンダー", "عرض"},
    }
    hints = verb_hints.get(primitive, set())
    if lemma.lower() in hints:
        base += 0.3
    # Boost si capability tiene side effects conocidos
    if contract.side_effects:
        base += 0.1
    return min(base, 1.0)


# ============================================================
# Registro global de discovery
# ============================================================

_global_engine: DiscoveryEngine | None = None


def get_discovery_engine() -> DiscoveryEngine:
    global _global_engine
    if _global_engine is None:
        _global_engine = DiscoveryEngine()
    return _global_engine


def discover(surface: str, lang: str, test_cases: list[dict]) -> Candidate | None:
    """Entry point simple: surface -> discover -> register."""
    engine = get_discovery_engine()
    return engine.discover_and_register(surface, lang, test_cases)


def enumerate_candidates(surface: str, lang: str) -> list[Candidate]:
    engine = get_discovery_engine()
    return engine.enumerate_candidates(surface, lang)


def verify_candidate(candidate: Candidate, test_cases: list[dict]) -> bool:
    engine = get_discovery_engine()
    return engine.verify_candidate(candidate, test_cases)


# ============================================================
# Test cases predefinidos para capabilities comunes
# ============================================================

DEFAULT_TEST_CASES: dict[str, list[dict]] = {
    "COPY": [
        {"inputs": {"src": "test_src.txt", "dst": "test_dst.txt"}, 
         "expected": {"copied": True}},
    ],
    "MOVE": [
        {"inputs": {"src": "test_src2.txt", "dst": "test_dst2.txt"}, 
         "expected": {"moved": True}},
    ],
    "REMOVE": [
        {"inputs": {"path": "test_to_delete.txt"}, 
         "expected": {"deleted": True}},
    ],
    "DOWNLOAD": [
        {"inputs": {"url": "https://example.com/test.txt", "dst": "downloaded.txt"}, 
         "expected": {"downloaded": True}},
    ],
    "RUN": [
        {"inputs": {"cmd": "echo test"}, 
         "expected": {"success": True}},
    ],
    "CONNECT": [
        {"inputs": {"host": "google.com", "port": 80}, 
         "expected": {"connected": True}},
    ],
}


def discover_from_unknown(surface: str, lang: str, 
                          custom_tests: dict[str, list[dict]] | None = None) -> Candidate | None:
    """Intenta descubrir primitiva desde surface que dio UNKNOWN."""
    tests = custom_tests or DEFAULT_TEST_CASES
    engine = get_discovery_engine()
    
    for cand in engine.enumerate_candidates(surface, lang):
        test_cases = tests.get(cand.primitive, [])
        if test_cases and engine.verify_candidate(cand, test_cases):
            engine.register_primitive(cand, test_cases)
            return cand
    return None