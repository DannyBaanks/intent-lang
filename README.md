# intent-lang

> Un lenguaje donde el idioma es una **representación superficial** de la
> intención, no la intención misma.

```
"agrega cuerpo"    "add body"    "添加身体"    "ajoute le corps"
```

No son cuatro instrucciones. Son cuatro maneras de expresar la misma intención
canónica.

**Estado: diseño, sin implementar.** Este repo es la especificación —
[`DESIGN.md`](DESIGN.md). El código viene después.

---

## La idea

Es más fácil pensar en el idioma que ya dominás que en uno aprendido. Casi
todos los lenguajes de programación tienen palabras clave en inglés, y eso es
una capa de fricción entre la persona y la máquina que nadie eligió.

La propuesta no es "programar en tu idioma" — eso ya existe (Scratch lo hace en
70+ lenguas) y cualquier LLM traduce intención a código. La propuesta es más
angosta y por eso más interesante:

> **Lenguaje natural como método de entrada a un núcleo diminuto y verificable,
> donde la ambigüedad no se adivina y el round-trip te muestra qué se entendió.**

Si el núcleo es chico, la traducción deja de ser un problema sin fondo y pasa a
ser verificable.

## Lo que lo hace distinto

**El diccionario no alcanza, y el diseño lo asume.** Para "agrega cuerpo", un
diccionario confirma que `agregar` significa añadir. No puede decir si `cuerpo`
es un cuerpo físico o un campo `body`. Por eso hay **dos autoridades**: el
léxico autoriza que la palabra existe y en qué sentido; una tabla finita y
auditable autoriza qué intenciones existen.

**El modelo propone, el léxico dispone.** Cuando el léxico falla, un LLM propone
lemas candidatos — y esos candidatos vuelven al léxico para ser validados. Una
propuesta que no existe en el diccionario se descarta sin apelación. "No inventa
significado" es estructural, no una promesa.

**La ambigüedad es un estado, no un error.** Cuatro estados, y sólo uno actúa:

```
RESOLVED     verbo y operando únicos             → único que puede actuar
AMBIGUOUS    >1 candidato sobrevivió validación  → pregunta
UNKNOWN      no está en el léxico, o no mapea    → no actúa
INCOMPLETE   verbo sí, operando requerido no     → pide el faltante
```

**El round-trip es una prueba, no un adorno.** El sistema te devuelve lo que
entendió usando una palabra **distinta** del mismo conjunto de sinónimos:

```
escribís   "agrégale cuerpo"
sistema    "Entendí: AÑADIR (cuerpo). ¿Correcto?"
                    └── otra palabra del MISMO synset
```

Si te devuelve exactamente tu palabra, la capa semántica no corrió y estás
viendo un passthrough de strings. Hay un test que lo verifica.

## Sobre la RAE

La primera versión de esta idea decía "estricto a la RAE". No funciona: el DLE
es un diccionario de definiciones en prosa para humanos, sin identificadores de
sentido estables ni API.

Lo que el diseño necesitaba —equivalencia de **conceptos**, no de palabras— ya
existe con otro nombre: un **índice interlingüe**. WordNet + Open Multilingual
WordNet unen los sentidos de decenas de idiomas al mismo id de concepto.

```
es "agregar" ──┐
en "add"     ──┼──►  mismo id ILI, sin idioma
zh "添加"     ──┘
```

Y regala una propiedad: los synsets **ya son clases de paráfrasis**.
`agregar / añadir / sumar / incorporar` comparten synset, así que convergen sin
que ningún modelo intervenga.

## Cómo se sabrá si funciona

```
separación      AUTOMÁTICO, debe ser 100%    dos intenciones distintas
                                             nunca comparten representación
convergencia    MEDIDO, se reporta           no reprueba
round-trip      HUMANO                       la barra de éxito
```

La convergencia sola es una métrica trampa: un sistema que mapea todo a `ADD`
converge perfecto y no sirve para nada. El fallo peligroso no es que dos
paráfrasis no converjan — es que dos intenciones **distintas** colapsen a la
misma representación. Por eso la separación es la única que puede reprobar el
build.

## Alcance de la v1

3 idiomas (español, inglés, chino) · 8 primitivas · sin ejecución · sin dominio.

Chino entra a propósito: no es indoeuropeo ni alfabético, así que si la
representación converge entre español y chino, converge de verdad. Con tres
lenguas europeas el resultado sería mucho más débil.

## Genealogía

Esto sale de [JAJAJA](https://github.com/DannyBaanks/JAJAJA), un esolang cuyo
alfabeto son repeticiones de `ja`.

```
JAJAJA       representación absurda   →  mismo contrato
intent-lang  representación humana    →  mismo contrato
```

Uno pregunta *"¿puedo ejecutar aunque la representación sea ridícula?"*.
El otro, *"¿puedo ejecutar sin obligar al humano a aprender una representación
artificial?"*. Mismo experimento, extremos opuestos.

*(El nombre del repo está en inglés y el diseño en español. Es coherente con la
tesis: la superficie no es la semántica.)*

## Licencia

MIT.
