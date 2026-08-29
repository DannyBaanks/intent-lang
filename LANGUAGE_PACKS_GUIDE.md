# Guía de Language Packs - Instalación y Troubleshooting

## Estado actual de idiomas (2026-08-28)

| Código | Idioma | WordNet | Tokenizer | Estado |
|--------|--------|---------|-----------|--------|
| es | Español | omw-es:1.4 | simplemma | ✅ Instalado |
| en | Inglés | omw-en:1.4 | simplemma | ✅ Instalado |
| zh | Chino | omw-cmn:1.4 | jieba | ✅ Instalado |
| ja | Japonés | omw-ja:1.4 | fugashi | ✅ Instalado |
| ar | Árabe | omw-arb:1.4 | simplemma | ✅ Instalado |
| fi | Finlandés | omw-fi:1.4 | simplemma | ✅ Instalado |
| he | Hebreo | omw-he:1.4 | simplemma | ✅ Instalado |
| tr | Turco | omw-tr:1.4 | simplemma | ⚠️ Placeholder (no OMW) |
| th | Tailandés | omw-th:2.0 | simplemma | ⚠️ Requiere descarga manual |
| vi | Vietnamita | omw-vi:1.4 | simplemma | ⚠️ No verificado |
| ru | Ruso | omw-ru:1.4 | pymorphy3 | ⚠️ No verificado |
| hi | Hindi | omw-hi:1.4 | simplemma | ⚠️ No verificado |
| ko | Coreano | omw-ko:1.4 | kiwi | ⚠️ No verificado |

## Instalación automática (cuando WordNet existe en OMW)

```bash
# Ver idiomas disponibles
engine-lang remote

# Instalar (descarga YAML + valida + verifica WordNet)
engine-lang install vi

# Forzar reinstalación
engine-lang install vi --force
```

## Problemas conocidos y soluciones manuales

### Tailandés (th) - WordNet omw-th:2.0 existe pero no se descarga automáticamente

**Síntoma:** `engine-lang install th` falla con "WordNet not available"

**Causa:** El registry no detecta el archivo th.yaml descargado, o wn.download no se ejecuta en el momento correcto.

**Solución manual:**

```bash
# 1. Descargar el wordnet thai
python -c "import wn; wn.download('omw-th:2.0')"

# 2. Descargar el YAML del language pack
python -c "
import urllib.request
url = 'https://raw.githubusercontent.com/DannyBaanks/intent-lang/main/language-packs/th.yaml'
urllib.request.urlretrieve(url, 'src/engine_lang/languages/th.yaml')
"

# 3. Recargar registry y verificar
python -c "
import sys
sys.path.insert(0, 'src')
from engine_lang.registry import reload
reg = reload()
print('th available:', reg.has_language('th'))
"
```

### Vietnamita (vi), Coreano (ko), Ruso (ru), Hindi (hi)

Estos idiomas tienen paquetes OMW listados pero no verificados. Para instalar:

```bash
# Verificar si WordNet existe en OMW
python -c "
import wn
for p in wn.projects():
    pid = p.get('id') if isinstance(p, dict) else getattr(p, 'id', '')
    if 'vi' in pid.lower() or 'ko' in pid.lower() or 'ru' in pid.lower() or 'hi' in pid.lower():
        print(pid)
"
```

Si existe el paquete, seguir el mismo procedimiento que Thai:
1. `python -c "import wn; wn.download('omw-vi:1.4')"` (ajustar versión)
2. Descargar YAML a `src/engine_lang/languages/vi.yaml`
3. `engine-lang install vi`

## Verificar instalación

```bash
# Listar instalados
engine-lang list

# Verificar todos
engine-lang verify

# Verificar uno específico
engine-lang verify th
```

## Verificar que el registry recarga correctamente

```bash
python -c "
import sys
sys.path.insert(0, 'src')
from engine_lang.registry import reload
reg = reload()
print('Supported:', reg.supported_languages)
print('Has th:', reg.has_language('th'))
"
```

## Troubleshooting común

| Error | Causa | Solución |
|-------|-------|----------|
| "Language not in registry" | YAML no en `src/engine_lang/languages/` | Descargar YAML manualmente |
| "WordNet not available" | wn.download no ejecutado o versión incorrecta | `python -c "import wn; wn.download('omw-XX:X.X')"` |
| "Already installed (use --force)" | YAML ya existe en local | `engine-lang install XX --force` |
| "Contract validation failed" | YAML malformado | Verificar YAML contra `engine_lang/contracts/language.v1.json` |

## Estructura de directorios

```
intent-lang/
├── language-packs/           # Source YAMLs (servidos via raw.githubusercontent.com)
│   ├── es.yaml
│   ├── th.yaml
│   └── ...
├── src/engine_lang/
│   ├── languages/            # Copia local instalada (lee el registry)
│   │   ├── es.yaml
│   │   ├── th.yaml
│   │   └── ...
│   ├── contracts/language.v1.json
│   └── registry.py
└── .github/workflows/ci.yml
```

## Flujo de instalación completo (automatizable)

```bash
#!/bin/bash
# install_lang.sh vi

LANG_CODE=$1
PY="python -c"

# 1. Verificar si existe en OMW
$PY "
import wn
found = False
for p in wn.projects():
    pid = p.get('id') if isinstance(p, dict) else getattr(p, 'id', '')
    if '$LANG_CODE' in pid.lower():
        print('Found:', pid)
        found = True
if not found:
    print('NOT FOUND in OMW')
    exit(1)
"

# 2. Descargar wordnet
$PY "import wn; wn.download('omw-$LANG_CODE:1.4')"

# 2. Descargar YAML
$PY "
import urllib.request
url = 'https://raw.githubusercontent.com/DannyBaanks/intent-lang/main/language-packs/$LANG_CODE.yaml'
urllib.request.urlretrieve(url, 'src/engine_lang/languages/$LANG_CODE.yaml')
"

# 3. Instalar
engine-lang install $LANG_CODE --force

# 4. Verificar
engine-lang verify $LANG_CODE
```

## Notas importantes

1. **El registry lee de `src/engine_lang/languages/`** - ahí es donde deben estar los YAMLs para que `engine-lang install` los detecte.

2. **`engine-lang install` hace 3 cosas:**
   - Descarga YAML del remote registry
   - Valida contra JSON Schema
   - Verifica que WordNet esté disponible (ejecuta `wn.Wordnet()`)

3. **WordNet se descarga a `~/.wordnet/`** - es cache global, no por proyecto.

3. **Si `engine-lang install` falla en WordNet pero `wn.Wordnet()` funciona en Python**, es un problema de timing del registry reload. Ejecutar `reload()` manualmente antes de verificar.

## Estado actual del repo

- **CI**: GitHub Actions (Windows + Linux, lint, build, evidence)
- **Remote registry**: `https://raw.githubusercontent.com/DannyBaanks/intent-lang/main/language-packs/`
- **13 language packs** en `language-packs/` + 8 instalados en `src/engine_lang/languages/`
- **Tests**: 83/83 passing
- **Executor**: Funcional con evidence SHA256
