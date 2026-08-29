"""Korean Semantic Backend: kiwipiepy + fallback semántico simple.

No hay wordnet coreano en OMW. Usamos kiwipiepy para tokenización
y un diccionario simple de semántica coreana.
"""
from __future__ import annotations

from .semantic import SemanticResult, SimilarityResult

# Diccionario semántico coreano simple (para compatibilidad con idiomas existentes)
# Formato: {palabra: [{"ili": "iXXXXX", "lemma": str, "pos": str, "definition": str}]}
KOREAN_SEMANTIC_DICT = {
    "파일": [{"ili": "i70665", "lemma": "파일", "pos": "n", "definition": "archivo"}],
    "복사": [{"ili": "i30214", "lemma": "복사", "pos": "v", "definition": "copiar"}],
    "삭제": [{"ili": "i26584", "lemma": "삭제", "pos": "v", "definition": "eliminar"}],
    "이동": [{"ili": "i30886", "lemma": "이동", "pos": "v", "definition": "mover"}],
    "복사하다": [{"ili": "i30214", "lemma": "복사하다", "pos": "v", "definition": "copiar"}],
    "삭제하다": [{"ili": "i26584", "lemma": "삭제하다", "pos": "v", "definition": "eliminar"}],
    "이동하다": [{"ili": "i30886", "lemma": "이동하다", "pos": "v", "definition": "mover"}],
    "실행": [{"ili": "i34510", "lemma": "실행", "pos": "v", "definition": "ejecutar"}],
    "실행하다": [{"ili": "i34510", "lemma": "실행하다", "pos": "v", "definition": "ejecutar"}],
    "복제": [{"ili": "i34961", "lemma": "복제", "pos": "v", "definition": "duplicar"}],
    "연결": [{"ili": "i25271", "lemma": "연결", "pos": "v", "definition": "conectar"}],
    "연결하다": [{"ili": "i25271", "lemma": "연결하다", "pos": "v", "definition": "conectar"}],
    "변경": [{"ili": "i22376", "lemma": "변경", "pos": "v", "definition": "cambiar"}],
    "변경하다": [{"ili": "i22376", "lemma": "변경하다", "pos": "v", "definition": "cambiar"}],
    "조회": [{"ili": "i32402", "lemma": "조회", "pos": "v", "definition": "consultar"}],
    "조회하다": [{"ili": "i32402", "lemma": "조회하다", "pos": "v", "definition": "consultar"}],
    "추가": [{"ili": "i22623", "lemma": "추가", "pos": "v", "definition": "agregar"}],
    "추가하다": [{"ili": "i22623", "lemma": "추가하다", "pos": "v", "definition": "agregar"}],
}


class KoreanSemantic:
    """Backend semántico coreano: kiwipiepy + diccionario ILI mapeado."""
    
    @property
    def name(self) -> str:
        return "korean"
    
    @property
    def supported_languages(self) -> set[str]:
        return {"ko"}
    
    def supports(self, language: str) -> bool:
        return language == "ko"
    
    def lookup(self, word: str, language: str, pos: str | None = None) -> SemanticResult:
        from .semantic import SemanticResult
        
        if not self.supports(language):
            from .semantic import UnsupportedLanguageError
            raise UnsupportedLanguageError("KoreanSemantic solo soporta: ko")
        
        # Usar kiwipiepy para tokenizar/lematizar
        try:
            import kiwipiepy
            kiwi = kiwipiepy.Kiwi()
            tokens = [
                token.lemma
                for token in kiwi.tokenize(word)
                if token.tag.startswith(('NNG', 'NNP', 'VV', 'VA', 'VX', 'XSV', 'XSA'))
            ]
        except Exception:
            tokens = [word]
        
        # Buscar en diccionario (usar lemas kiwi o palabra original)
        senses_data = []
        search_terms = [*tokens, word]
        seen_ili = set()
        
        for term in search_terms:
            if term in KOREAN_SEMANTIC_DICT:
                for sense in KOREAN_SEMANTIC_DICT[term]:
                    if sense["ili"] not in seen_ili:
                        seen_ili.add(sense["ili"])
                        senses_data.append(sense)
        
        # Si no hay coincidencia, devolver sense genérico
        if not senses_data:
            senses_data = [{
                "ili": "i_unknown",
                "lemma": word,
                "pos": pos or "unknown",
                "definition": "",
            }]
        
        return SemanticResult(
            word=word,
            language="ko",
            backend="korean",
            senses=senses_data,
        )
    
    def similarity(self, word_a: str, word_b: str, language: str) -> SimilarityResult:
        from .semantic import SimilarityResult
        
        if not self.supports(language):
            from .semantic import UnsupportedLanguageError
            raise UnsupportedLanguageError("KoreanSemantic solo soporta: ko")
        
        # Buscar ILIs compartidos en nuestro diccionario
        ilis_a = set()
        ilis_b = set()
        
        for term, senses in KOREAN_SEMANTIC_DICT.items():
            if word_a in term or term in word_a:
                for s in senses:
                    ilis_a.add(s["ili"])
            if word_b in term or term in word_b:
                for s in senses:
                    ilis_b.add(s["ili"])
        
        shared = ilis_a & ilis_b
        score = 1.0 if shared else 0.0
        
        return SimilarityResult(
            word_a=word_a,
            word_b=word_b,
            language=language,
            backend="korean",
            score=score,
            method="korean_dict_overlap",
        )
    
    def relations(self, word: str, language: str, relation_type: str | None = None) -> list[dict]:
        # Placeholder: relaciones coreanas no implementadas
        return []
