"""Thai Semantic Backend: simplemma + ILI mapping diccionario.

Thai tiene wordnet omw-th:2.0 pero este backend demuestra el patrón
para idiomas con/sin wordnet.
"""
from __future__ import annotations

from .semantic import SemanticResult, SimilarityResult, UnsupportedLanguageError

# Diccionario semántico tailandés simple (mapeado a ILIs de wordnet)
THAI_SEMANTIC_DICT = {
    "ไฟล์": [{"ili": "i70665", "lemma": "ไฟล์", "pos": "n", "definition": "archivo"}],
    "คัดลอก": [{"ili": "i30214", "lemma": "คัดลอก", "pos": "v", "definition": "copiar"}],
    "ลบ": [{"ili": "i26584", "lemma": "ลบ", "pos": "v", "definition": "eliminar"}],
    "ย้าย": [{"ili": "i30886", "lemma": "ย้าย", "pos": "v", "definition": "mover"}],
    "คัดลอกไฟล์": [{"ili": "i30214", "lemma": "คัดลอก", "pos": "v", "definition": "copiar"}],
    "ลบไฟล์": [{"ili": "i26584", "lemma": "ลบ", "pos": "v", "definition": "eliminar"}],
    "ย้ายไฟล์": [{"ili": "i30886", "lemma": "ย้าย", "pos": "v", "definition": "mover"}],
    "ดาวน์โหลด": [{"ili": "i34510", "lemma": "ดาวน์โหลด", "pos": "v", "definition": "descargar"}],
    "คอมไพล์": [{"ili": "i34510", "lemma": "คอมไพล์", "pos": "v", "definition": "compilar"}],
    "เรนเดอร์": [{"ili": "i34510", "lemma": "เรนเดอร์", "pos": "v", "definition": "renderizar"}],
    "รัน": [{"ili": "i34510", "lemma": "รัน", "pos": "v", "definition": "ejecutar"}],
    "คอมไพล์โค้ด": [{"ili": "i34510", "lemma": "คอมไพล์", "pos": "v", "definition": "compilar"}],
    "ทดสอบ": [{"ili": "i32402", "lemma": "ทดสอบ", "pos": "v", "definition": "test"}],
    "เพิ่ม": [{"ili": "i22623", "lemma": "เพิ่ม", "pos": "v", "definition": "agregar"}],
    "เชื่อมต่อ": [{"ili": "i25271", "lemma": "เชื่อมต่อ", "pos": "v", "definition": "conectar"}],
    "เปลี่ยน": [{"ili": "i22376", "lemma": "เปลี่ยน", "pos": "v", "definition": "cambiar"}],
    "ค้นหา": [{"ili": "i32402", "lemma": "ค้นหา", "pos": "v", "definition": "buscar"}],
    "เพิ่มข้อมูล": [{"ili": "i22623", "lemma": "เพิ่ม", "pos": "v", "definition": "agregar"}],
}


class ThaiSemantic:
    """Backend semántico tailandés: simplemma + diccionario ILI."""
    
    @property
    def name(self) -> str:
        return "thai"
    
    @property
    def supported_languages(self) -> set[str]:
        return {"th"}
    
    def supports(self, language: str) -> bool:
        return language == "th"
    
    def lookup(self, word: str, language: str, pos: str | None = None) -> SemanticResult:
        from .semantic import SemanticResult
        
        if not self.supports(language):
            raise UnsupportedLanguageError("ThaiSemantic solo soporta: th")
        
        # Usar simplemma para lematizar
        try:
            import simplemma
            lemma = simplemma.lemmatize(word, lang='th')
            tokens = [lemma, word]
        except Exception:
            tokens = [word]
        
        senses_data = []
        seen_ili = set()
        
        for term in tokens:
            if term in THAI_SEMANTIC_DICT:
                for sense in THAI_SEMANTIC_DICT[term]:
                    if sense["ili"] not in seen_ili:
                        seen_ili.add(sense["ili"])
                        senses_data.append(sense)
        
        if not senses_data:
            senses_data = [{
                "ili": "i_unknown",
                "lemma": word,
                "pos": pos or "unknown",
                "definition": "",
            }]
        
        return SemanticResult(
            word=word,
            language="th",
            backend="thai",
            senses=senses_data,
        )
    
    def similarity(self, word_a: str, word_b: str, language: str) -> SimilarityResult:
        from .semantic import SimilarityResult
        
        if not self.supports(language):
            raise UnsupportedLanguageError("ThaiSemantic solo soporta: th")
        
        ilis_a = set()
        ilis_b = set()
        
        for term, senses in THAI_SEMANTIC_DICT.items():
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
            backend="thai",
            score=score,
            method="thai_dict_overlap",
        )
    
    def relations(self, word: str, language: str, relation_type: str | None = None) -> list[dict]:
        return []
