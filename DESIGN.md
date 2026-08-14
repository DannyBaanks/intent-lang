# Lenguaje de intención — diseño

Fecha: 2026-08-14
Estado: diseño aprobado, sin implementar todavía
Origen: consecuencia directa de [JAJAJA](https://github.com/DannyBaanks/JAJAJA)

---

## 1. Qué es

Un lenguaje donde **el idioma es una representación superficial de la
intención**, no la intención misma.

```
"agrega cuerpo"   "add body"   "添加身体"   "ajoute le corps"
```

no son cuatro instrucciones. Son cuatro maneras de expresar la misma intención
canónica. El sistema resuelve cualquiera de ellas a una representación interna
**sin idioma**, y devuelve al humano lo que entendió, en su lengua.

### La simetría con JAJAJA

```
JAJAJA          representación absurda   →  mismo contrato
Intención       representación humana    →  mismo contrato
```

JAJAJA preguntó *"¿puedo ejecutar aunque la representación sea ridícula?"*.
Este pregunta *"¿puedo ejecutar sin obligar al humano a aprender una
representación artificial?"*. Mismo experimento, extremos opuestos.

## 2. Qué NO es

- **No es un traductor de frases a código.** Eso ya lo hace cualquier LLM y no
  aporta nada nuevo. La superficie natural entra a un núcleo diminuto y
  verificable, no a un lenguaje de propósito general.
- **No es un chatbot disfrazado de compilador.** El sistema no adivina. Si la
  intención no está determinada, no produce acción.
- **No es "el modelo entiende cualquier cosa".** Hay una autoridad léxica
  explícita y el modelo no puede pasarla por encima.

## 3. Decisión: la RAE no sirve para esto

El DLE es un diccionario de definiciones en prosa para humanos: sin
identificadores de sentido estables, sin API, con restricciones de uso. Sirve
como referencia de "esta palabra existe en español"; no como capa semántica
mecanizable.

Lo que el diseño necesita —equivalencia de **conceptos**, no de palabras— ya
existe con otro nombre: un **índice interlingüe**.

```
WordNet (Princeton) + Open Multilingual WordNet, unidos por el ILI

es "agregar" ──┐
en "add"     ──┼──►  ILI concept id   (sin idioma)
zh "添加"     ──┘
```

Alternativa evaluada: **Wikidata** (items Q, sin idioma, CC0). Se elige OMW/ILI
para la v1 porque trae synsets —conjuntos de sinónimos— que el diseño usa dos
veces: para converger paráfrasis y para la re-lexicalización del round-trip.

**Consecuencia:** los synsets son clases de paráfrasis gratis.
`agregar/añadir/sumar/incorporar` comparten synset → comparten ILI → misma
primitiva, sin modelo de por medio.

## 4. Las dos autoridades

Ésta es la corrección central del diseño original. El léxico **no puede** hacer
toda la desambiguación.

Para "agrega cuerpo", el diccionario confirma que `agregar` significa añadir.
No puede decir si `cuerpo` es un cuerpo físico o un campo `body`. Eso es
ambigüedad de **dominio**, no léxica.

```
AUTORIDAD LÉXICA        ¿existe la palabra? ¿en qué sentido?
                        fuente: Open Multilingual WordNet

AUTORIDAD DE INTENCIÓN  ¿existe esa intención?
                        fuente: tabla concepto ILI → primitiva
```

La mayoría de los `AMBIGUOUS` / `INCOMPLETE` salen de la segunda.

## 5. Arquitectura

Seis capas. El LLM vive en la 3 y no emite representación.

```
   TEXTO HUMANO
        │
   [1] NORMALIZADOR      es/en: lematizar · zh: segmentar
        ↓
   [2] LÉXICO ◄──────────┐   AUTORIDAD LÉXICA
        │  lema → synset → ILI
        ├── falla ────► [3] PROPONENTE (LLM)
        │                 │   propone lemas candidatos
        │                 └───┘ que vuelven a [2] para validar
        ↓
   [4] ENSAMBLADOR           AUTORIDAD DE INTENCIÓN
        │  concepto ILI → primitiva
        ↓
   [5] RESOLUTOR
        │  RESOLVED · AMBIGUOUS · UNKNOWN · INCOMPLETE
        ↓
   [6] RE-LEXICALIZADOR
           IR → palabra distinta del mismo synset
```

**Regla dura:** el LLM propone, el léxico dispone. Una propuesta que no existe
en el wordnet, o que existe pero no mapea a primitiva, se descarta sin
apelación. "No inventa significado" es estructural, no una promesa.

## 6. La representación canónica

```json
{
  "schema": "intent/1",
  "verb":    { "ili": "i35760", "primitive": "ADD" },
  "operand": { "ili": "i52341", "lemma_es": "cuerpo" },
  "scope":   null,
  "status":  "INCOMPLETE",
  "provenance": {
    "surface":        "agrégale cuerpo",
    "language":       "es",
    "lexical_source": "omw-es-1.4",
    "resolution":     "lexicon",
    "confidence":     "exact",
    "mode":           "strict",
    "cache_key":      null
  }
}
```

La `provenance` es obligatoria y completa: si una interpretación resulta
incorrecta, tiene que poder rastrearse exactamente qué capa la produjo.

### Primitivas

Ocho, cada una anclada a un synset real:

```
ADD · REMOVE · MOVE · CHANGE · QUERY · RUN · COPY · CONNECT
```

La tabla `concepto ILI → primitiva` **se escribe a mano**. Ahí vive todo el
juicio humano del sistema, y por eso debe ser chica y auditable de una sentada.
Es la pieza que alguien puede leer entera y decir "sí, esto es lo que
significa".

### Estados, y cuál ejecuta

```
RESOLVED     verbo y operando únicos            → único que puede volverse acción
AMBIGUOUS    >1 candidato sobrevivió validación → pide aclaración
UNKNOWN      no está en el léxico, o no mapea   → no actúa
INCOMPLETE   verbo sí, operando requerido no    → pide el faltante
```

**Aridad, para que `INCOMPLETE` sea decidible:** las ocho primitivas exigen
verbo + operando. `scope` es siempre opcional en la v1 — sin dominio no hay
contra qué validarlo, así que se guarda si aparece y no se exige nunca. Una IR
sin operando es `INCOMPLETE`; una IR sin `scope` puede ser `RESOLVED`.

Sólo `RESOLVED` puede convertirse en una acción. Todo lo demás es no-acción:
deny por defecto aplicado al significado.

## 7. El round-trip como prueba, no como adorno

El round-trip **no usa plantillas**. Toma el id ILI y elige una palabra del
synset, preferentemente **distinta** a la que escribió el usuario.

```
escribís   "agrégale cuerpo"
           ↓ agregar → synset → i35760
sistema    "Entendí: AÑADIR (cuerpo). ¿Correcto?"
                     └── otra palabra del MISMO synset
```

Si devuelve *añadir* cuando escribiste *agrégale*, la capa semántica trabajó.
Si devuelve exactamente tu palabra, estás viendo un passthrough de strings.

Cruzando idiomas es más fuerte todavía: se escribe en español, se devuelve en
chino, y si el hablante de chino dice "sí", convergieron de verdad.

## 8. Determinismo: dos modos

```
strict     sólo léxico. 100% determinista. Línea base reproducible.
assisted   con caché de propuestas. Un hit es determinista;
           un miss produce un hecho nuevo, firmado.
```

Cada propuesta del LLM se congela como evidencia:

```json
{ "key":       { "surface":"métele", "language":"es",
                 "lexicon":"omw-es-1.4", "model":"claude-opus-5" },
  "proposed":  ["agregar","insertar","forzar"],
  "validated": ["agregar","insertar"],
  "rejected":  [{"lemma":"forzar","reason":"no mapea a primitiva"}],
  "evidence_sha256": "..." }
```

El modo usado queda escrito en la provenance de cada IR. Nunca se infiere.

El LLM es **front-end de compilador que corre una vez**, no dependencia de
runtime. Nunca está en el camino de ejecución.

## 9. Errores: todo falla cerrado

```
idioma no detectado             → pregunta, no adivina
falta el wordnet de un idioma   → error al arrancar, NO degrada en silencio
LLM caído                       → cae a `strict` Y LO ESCRIBE en la provenance
```

Degradar está permitido. Degradar callado, no. Es la lección directa de dos
dos fallos vistos de cerca: comprobaciones que quedaban en no-op según el
directorio desde el que corrías, y un `except: pass` que mataba una protección
anti-replay sin dejar rastro. Los dos pasaban en verde.

## 10. Cómo se sabe si funciona

```
separación      AUTOMÁTICO, debe ser 100%    invariante de seguridad
                dos intenciones distintas nunca comparten IR
                si se rompe, el build se cae

convergencia    MEDIDO, se reporta           no reprueba
                % de paráfrasis que llegan a la misma IR

round-trip      HUMANO                       la barra de éxito
                cada juicio se guarda como caso etiquetado

determinismo    mismo input en `strict` → IR byte-idéntica
```

**Convergencia sola es una métrica trampa.** Un sistema que mapea todo a `ADD`
converge perfecto y no sirve. El fallo peligroso no es que dos paráfrasis no
converjan: es que dos intenciones **distintas** colapsen a la misma IR. Por eso
separación es invariante y convergencia sólo se reporta.

El round-trip humano y el corpus automático no compiten: **cada juicio humano
se convierte en caso etiquetado**, así que la métrica humana arranca el corpus
que después corre solo como regresión.

### Test propio del enfoque

```
si el synset tiene ≥2 miembros, la palabra del round-trip
DEBE ser distinta a la que escribió el usuario
```

Convierte al round-trip en detector de fraude del propio sistema.

## 11. Alcance de la v1

**Adentro:**
- 3 idiomas: español, inglés, chino
- 8 primitivas
- IR canónica + provenance completa
- Los 4 estados, con no-acción para todo lo que no sea `RESOLVED`
- Round-trip por re-lexicalización
- Modos `strict` y `assisted` con caché firmado
- Arnés de juicio humano que escribe corpus

**Afuera, a propósito:**
- **Ejecución.** La salida es la IR y el round-trip. No se conecta a nada.
- **Dominio.** Sin catálogo de operaciones ni ontología de objetos. El núcleo
  es abstracto; el dominio se enchufa después como tabla aparte.
- Más idiomas. Se agregan sin tocar el runtime: lematizador + wordnet + nada más.

Chino entra en la v1 a propósito y no por ambición: es no indoeuropeo y no
alfabético, así que si la IR converge entre español y chino, converge de
verdad. Con tres lenguas europeas el resultado sería mucho más débil.

## 12. Riesgos conocidos

| Riesgo | Mitigación |
|---|---|
| Cobertura baja: mucho `UNKNOWN` en v1 | Es aceptable y se mide. La cobertura es trabajo posterior, no criterio de aprobación |
| La tabla concepto→primitiva crece sin control | Las primitivas son 8 y no se tocan; lo que crece es la tabla de conceptos que mapean a ellas (muchos conceptos → una primitiva). Techo duro ~50 entradas: pasarlo es señal de que falta un dominio, no más primitivas |
| El caché del LLM se vuelve la fuente real | El modo `strict` sin caché debe seguir corriendo verde siempre. Es la línea base |
| Chino sin lematización | Segmentación en su lugar. Si la calidad no alcanza, se reporta como limitación, no se disimula |
| Falsa convergencia por primitivas demasiado gruesas | La invariante de separación la caza. Es el único test que puede reprobar el build |

## 13. Preguntas abiertas

- ¿La tabla concepto→primitiva se escribe a mano entera, o se siembra desde los
  hiperónimos del ILI y se corrige a mano? Lo segundo es más rápido y menos
  auditable.
- El operando se resuelve a ILI **y** se guarda el lema de superficie (§6). Lo
  que queda abierto es si resolverlo debe ser *obligatorio*: hoy un operando que
  no resuelve a ILI cae en `UNKNOWN`, lo que puede ser demasiado estricto para
  nombres propios y jerga técnica ("agrega un getter"). Alternativa a evaluar:
  operando sin ILI pero con lema, marcado `confidence: "surface_only"`.
- ¿Qué pasa con lenguas sin wordnet en OMW? Hoy: no se soportan. Habría que
  decidir si eso es permanente o si hay una vía de alta.
