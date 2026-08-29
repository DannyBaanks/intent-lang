# Guía de la interfaz web

```powershell
py web/server.py
```

Abre `http://127.0.0.1:8765` en el navegador.

Para levantar la demo estática con Docker:

```powershell
docker compose up -d
```

Abre `http://127.0.0.1:8080`.

**Regla:** esta pantalla solo resuelve y muestra el `Intent IR`; no ejecuta
capabilities ni produce efectos en el sistema.

## Comandos

### Arrancar el servidor

```text
py web/server.py
intent-lang web: http://127.0.0.1:8765
```

La segunda línea es la dirección local. Detén el servidor con `Ctrl+C`.

### Resolver desde la interfaz

Escribe una intención en el cuadro izquierdo y pulsa `Resolver intención`.
La interfaz llama al endpoint local `/api/resolve` y muestra el estado, el IR,
el round-trip y una traza de lectura.

Salida verificada desde un cliente UTF-8:

```text
HTTP=200 STATUS=RESOLVED ROUNDTRIP=Entendí: ADICIONAR (cuerpo). ¿Correcto?
```

## Estados

| Estado | Significado | Acción |
|---|---|---|
| `RESOLVED` | verbo y operando únicos | revisar el round-trip |
| `AMBIGUOUS` | sobrevivieron varios candidatos | cambiar la frase o decidir manualmente |
| `UNKNOWN` | no hay lema o concepto válido | usar una palabra soportada |
| `INCOMPLETE` | falta un operando requerido | completar la intención |
| `ERROR` | fallo del endpoint local | revisar la consola del servidor |

## Trampas

- `py web/server.py` debe ejecutarse desde la raíz del repositorio.
- El navegador envía JSON UTF-8. Una petición manual desde PowerShell puede
  codificar caracteres como `é` en Windows-1252 si no se construye el cuerpo
  explícitamente en UTF-8.
- `Resolver intención` no ejecuta `WRITE`, `COPY`, `DELETE` ni ninguna otra
  capability; para eso se usa el flujo de ejecución del paquete, no esta UI.
- En GitHub Pages y Docker la interfaz funciona como demo estática. Solo los
  ejemplos incluidos tienen resultado local; para resolver texto arbitrario
  usa `py web/server.py`.
