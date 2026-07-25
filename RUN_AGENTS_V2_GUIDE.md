# run_agents_v2.py — Pipeline multi-agente stack-agnóstico

Orquestador de agentes opencode para backend y frontend. Detecta el stack
automáticamente, valida con Playwright headless (frontend) o `mvn test`/`npm test`/etc.
(backend). Genera SDD automáticamente al final.

## Requisitos

- Python 3.10+
- Node.js + npm (para Playwright headless en proyectos frontend)
- opencode instalado globalmente

## Instalación y path del script

El script vive en `C:\WorkSpace\Scritp-python\run_agents_v2.py`.

Recomendación: crear un alias en PowerShell para no escribir la ruta completa:

```powershell
# PowerShell $PROFILE
function Run-Pipeline {
    python C:\WorkSpace\Scritp-python\run_agents_v2.py $args
}
```

## Uso básico

```powershell
# Objetivo corto (directo en línea de comandos)
python C:\WorkSpace\Scritp-python\run_agents_v2.py C:\WorkSpace\mi-proyecto "Implementar login con JWT"

# Objetivo largo desde archivo (recomendado para specs complejas)
python C:\WorkSpace\Scritp-python\run_agents_v2.py C:\WorkSpace\mi-proyecto --objective-file spec.md
```

## Forma recomendada: archivo de objetivo

Para objetivos con más de 1 línea o caracteres especiales (emojis, acentos,
backticks), usa `--objective-file` en vez de pasar texto en argv. Evita
problemas de encoding/quoting:

```powershell
python C:\WorkSpace\Scritp-python\run_agents_v2.py C:\WorkSpace\RPG-Frontend --objective-file objetivo-animaciones.md
```

El archivo se lee byte-for-byte desde la raíz del proyecto (ruta relativa
al proyecto, no al script).

## Flags

| Flag | Descripción |
|---|---|
| `--resume` | Retoma una corrida anterior. Conserva `.opencode-context.md` y salta agentes que ya tienen marker |
| `--objective-file <path>` | Lee el objetivo desde un archivo (ruta relativa al proyecto). Usa `-` para stdin |
| `--help` | Muestra la ayuda completa |

## Ejemplos por stack

### Frontend HTML/JS/CSS vanilla

```powershell
python C:\WorkSpace\Scritp-python\run_agents_v2.py C:\WorkSpace\RPG-Frontend --objective-file objetivo-animaciones.md
```

- **Stack detectado**: `html_playwright`
- **Validación automática**: Playwright headless contra `index.html` (sin errores de consola)
- **Archivos de test**: si existen `__animation_tests.js`, se dejan intactos
- **Tiempo típico**: ~5-10min (Explorer 25s + Coder 5-20min + Tester 3-8min + SDD 1-2min)

### Java/Maven

```powershell
python C:\WorkSpace\Scritp-python\run_agents_v2.py C:\WorkSpace\mi-servicio --objective-file tarea.md
```

- **Stack detectado**: `maven` (por `pom.xml`)
- **Validación automática**: `mvn.cmd test -q` (o `mvnw.cmd` si existe el wrapper)
- **Tiempo típico**: variable según tests

### Node.js (npm/pnpm/yarn)

```powershell
python C:\WorkSpace\Scritp-python\run_agents_v2.py C:\WorkSpace\mi-app --objective-file tarea.md
```

- **Stack detectado**: `npm`/`pnpm`/`yarn` (por `package.json` + lockfile)
- **Validación automática**: `npm test` si existe el script, o `npm run build` si no
- **Nota**: no instala dependencias automáticamente

### Python/pytest

```powershell
python C:\WorkSpace\Scritp-python\run_agents_v2.py C:\WorkSpace\mi-proyecto --objective-file tarea.md
```

- **Stack detectado**: `pytest` (por `pyproject.toml`/`requirements.txt` + archivos `test_*.py`)
- **Validación automática**: `pytest -q`

### Go

```powershell
python C:\WorkSpace\Scritp-python\run_agents_v2.py C:\WorkSpace\mi-servicio --objective-file tarea.md
```

- **Stack detectado**: `go` (por `go.mod`)
- **Validación automática**: `go test ./...`

### .NET

```powershell
python C:\WorkSpace\Scritp-python\run_agents_v2.py C:\WorkSpace\mi-servicio --objective-file tarea.md
```

- **Stack detectado**: `dotnet` (por `*.csproj`/`*.sln`)
- **Validación automática**: `dotnet test --nologo -v q`

## Retomar tras fallo (--resume)

Si el pipeline se cae a mitad (por timeout, error de red, cierre de terminal):

```powershell
# Ver el último log para saber en qué agente falló
Get-Content "C:\WorkSpace\RPG-Frontend\pipeline-artifacts\pipeline-*.log" -Tail 5

# Relanzar con --resume para saltar agentes ya completados
python C:\WorkSpace\Scritp-python\run_agents_v2.py C:\WorkSpace\RPG-Frontend --objective-file objetivo.md --resume
```

`--resume` conserva `.opencode-context.md` existente y salta los agentes
que ya tienen su marker `<!-- AGENT_DONE: <agente> -->`.

## Pipeline completo: flujo

El script ejecuta 5 agentes en orden:

```
1. @explorer       → analiza estructura y stack, deja contexto
2. @coder          → implementa código según objetivo
3. @tester         → genera tests (o nota de validación manual)
4. @debugger       →  ← solo si tests fallan (hasta 3 reintentos)
5. @sdd-updater    → documenta en docs/context/global.md
```

Cada agente escribe su marker `<!-- AGENT_DONE: <agente> -->` al final del
`.opencode-context.md`. El script los usa para saber si puede saltar al
siguiente.

## Salida y artefactos

### Log persistente

Cada corrida genera un log en `pipeline-artifacts/pipeline-<timestamp>.log`
con timestamp, nivel, y snippet de errores por agente si rc≠0.

### Backups de contexto

Cada inicio de pipeline respalda el `.opencode-context.md` existente en
`pipeline-artifacts/context-history/.opencode-context.md.<timestamp>.bak`.

### SDD

El pipeline genera/actualiza `docs/context/global.md` con el estado actual
del proyecto, decisiones técnicas y criterios de aceptación cumplidos.

## Caché de Playwright

La primera corrida en un proyecto frontend instala Playwright en
`~/.opencode/playwright-cache/`. Las corridas posteriores reusan el caché
(saltan `npm i playwright`, ahorrando ~30-60s cada vez).

Para limpiar el caché (por corrupción o cambio de versión):

```powershell
Remove-Item -Recurse -Force "$env:USERPROFILE\.opencode\playwright-cache"
```

## Modelos de IA configurados

| Agente | Modelo | Propósito |
|---|---|---|
| explorer | opencode-go/deepseek-v4-flash | Rápido, análisis |
| coder | opencode-go/qwen3.7-plus | Código directo |
| tester | opencode-go/qwen3.7-plus | Pruebas |
| debugger | opencode-go/kimi-k2.7-code | Debug reactivo |
| sdd-updater | opencode-go/deepseek-v4-flash | Documentación |

Puedes sobrescribirlos editando las constantes `MODEL_FAST`, `MODEL_CODING`,
`MODEL_DEBUG` y el diccionario `AGENT_MODELS` al inicio del script.

## Timeouts por agente

| Agente | Timeout default | Cómo sobrescribir |
|---|---|---|
| explorer, tester, debugger, sdd-updater | 20 min | `$env:OC_AGENT_TIMEOUT_EXPLORER = 600` |
| coder | 40 min | `$env:OC_AGENT_TIMEOUT_CODER = 3600` |

Env vars: `OC_AGENT_TIMEOUT_<AGENTE_EN_MAYUSCULAS>`.

## Portabilidad (macOS / Linux)

Por default el script usa `C:\Users\Silvi\...\opencode.exe` (Windows).
Para otros sistemas, define la variable de entorno:

```bash
# bash/zsh
export OPENCODE_BIN="opencode"
python ~/scripts/run_agents_v2.py ~/proyecto "objetivo"
```

```powershell
# PowerShell (cualquier SO)
$env:OPENCODE_BIN = "opencode"
python ~/scripts/run_agents_v2.py ~/proyecto "objetivo"
```

## Troubleshooting

### "El agente no escribió su marker"

El orquestador inyecta el marker automáticamente si el agente terminó con
rc=0 pero no dejó marker. Ver el log:

```powershell
Select-String "Inyectando marker|P12 fix" "pipeline-artifacts\pipeline-*.log"
```

Si aparece, el agente ignoró la instrucción de cierre. Revisa el prompt
del agente en `~/.config/opencode/agents/<agente>.md`.

### Pipeline se queda colgado sin output

Probablemente el agente está en un comando bloqueante (`npx http-server`,
`npm run dev`, etc.). Mata con Ctrl-C y relanza con `--resume`.
Los prompts parchados ya instruyen a los agentes a no correr servidores
foreground — si persiste, verifica que tu versión de los agentes `.md`
tenga la regla "Sin Servidores en Foreground".

### Playwright falla en frontend vanilla

```powershell
# Ver el error exacto en el log más reciente
Get-Content "pipeline-artifacts\pipeline-*.log" | Select-String "Playwright" -Context 0,5
```

Causas comunes:
- El `http-server` no arrancó a tiempo (subir deadline en `_run_playwright_headless`)
- Errores de consola JS reales en el proyecto (revisar el snippet en el log)
- Puerto ocupado (matar procesos viejos con `taskkill /F /IM node.exe`)

### Error de sintaxis: `SyntaxError: unterminated string literal`

Fallo de encoding al pasar el objetivo como arg en PowerShell. Usa `--objective-file`.

## Historial de cambios del script

| Fecha | Cambio |
|---|---|
| 2026-07-25 | Creación inicial. Marker canónico, stack auto-detect, Playwright headless |
| 2026-07-25 | Fix rc=1 spurio Windows (apuntar al .exe directo, no al .cmd wrapper) |
| 2026-07-25 | PAUD-003: `try/except` + `atexit` envolviendo `__main__`. Captura de stderr en rc≠0 |
| 2026-07-25 | Stream en vivo del agente en terminal (Popen + thread reader) |
| 2026-07-25 | PAUD-008: Caché persistente Playwright en `~/.opencode/playwright-cache/` |
| 2026-07-25 | Timeout por agente (coder=2400s) + override vía env vars |
| 2026-07-25 | Agentes parchados con regla "JAMÁS escribir markers de otros agentes" |
