# multi-agent-pipeline

Orquestación multi-agente con **control de tokens y factura estimada**, sin la
caja negra de los asistentes de pago por suscripción.

Pipeline agnóstico de stack que coordina agentes opencode en secuencia
(Explorer → Coder → Tester → Debugger → SDD-Updater), cada uno escribiendo su
resultado en un contexto compartido, con verificación robusta de que cada fase
realmente terminó (markers + returncode), reintentos y un presupuesto de
contexto inyectado para mantener los costos a raya.

> ¿Por qué existe? La mayoría de soluciones "automatizan todo" de pago (~$20/mes,
> agentes opacos) no permiten controlar el gasto en tokens ni trazabilidad de lo
> que pasó. Este pipeline apunta a lo contrario: **control fino de costos + un
> registro preciso de cada corrida**.

## Para quién es

* Desarrolladores que corren agentes **opencode** en sus proyectos propios
* Equipos que quieren auditar **cuánto cuesta y qué hizo** cada corrida de IA
* Quien prefiere comprender y controlar la orquestación en vez de pagar por una caja cerrada

## Requisitos

* **Python 3.10+**
* **opencode** instalado y configurado (los agentes `.md` usan el directorio de agentes de tu ~/.config/opencode, o la env `OPENCODE_AGENTS_DIR`)
* **Node.js + npm** solo si validas frontend vanilla con Playwright headless
* Un stack detectado entre: Maven/Gradle, pytest, npm/pnpm/yarn, go, dotnet, HTML/JS/CSS vanilla

## Quick start

```bash
# 1. Instala el paquete (desde el repo)
pip install -e .

# 2. Objetivo corto (directo en argv)
pipeline run /ruta/a/mi-proyecto "Implementar login con JWT"

# 3. Objetivo largo desde archivo (recomendado para specs — evita problemas de quoting)
pipeline run /ruta/a/mi-proyecto --objective-file spec.md

# 4. Retomar una corrida interrumpida (salta agentes ya completados)
pipeline resume /ruta/a/mi-proyecto --objective-file spec.md

# 5. Consultar estado y costo de la última corrida
pipeline status /ruta/a/mi-proyecto
pipeline cost /ruta/a/mi-proyecto
```

También puedes correr el script directamente sin instalarlo:

```bash
python run_agents_v2.py run /ruta/a/mi-proyecto "Implementar login con JWT"
```

> Nota: la sintaxis es `pipeline run <proyecto> "objetivo"`. El comando posicional
> legacy (`pipeline <proyecto> "objetivo"` sin `run`) quedó fuera en F3.

Si usas PowerShell, define un alias para no escribir la ruta completa:

```powershell
function Run-Pipeline { python C:\WorkSpace\Scritp-python\run_agents_v2.py $args }
```

## Qué hace por cada corrida

1. **Backup** del contexto previo (nunca pisa trabajo sin copia)
2. **Detecta el stack** del proyecto (Maven, pytest, npm, go, dotnet, frontend)
3. Ejecuta la cadena de agentes, cada fase validada antes de avanzar
4. **Re-detecta el stack** tras implementar — si el código añadió un runner nuevo
(package.json, pom.xml, wrapper), los tests usan el correcto
5. **Valida** resultados reales (tests backend / Playwright headless frontend)
6. Si los tests fallan, entra un **bucle Debugger** (hasta 3 reintentos con el error real)
7. Actualiza la documentación (SDD) del proyecto — si no se completa, lo avisa
8. Escribe el **log persistente**, el **pipeline-status.json** y el **reporte de costo estimado**

## Control de costos

|Mecanismo|Efecto|
|-|-|
|`--mcp-minimal`|Deshabilita tool-schemas de MCP globales en cada request (ahorro por request)|
|`--budget-inject <N>`|Presupuesto de tokens por agente para el contexto inyectado (default 9000; `0` lo desactiva)|
|Reporte de costo|Factura estimada en USD por modelo al final de cada corrida|
|Modelos por agente|Configurables en `AGENT_MODELS` / `MODEL_PRICING`|

## Señales de salida (para CI / wrappers)

* **Exit code** indica la fase que falló: `2` explorer · `3` coder · `4` tester · `5` debugger · `6` sdd-updater · `0` éxito.
* **`pipeline-status.json`** en la raíz del proyecto con el último paso completado, la fase que falló y el log.
* **Log** persistente en `pipeline-artifacts/pipeline-<timestamp>.log`.

## Documentación

* **`README.md`** — presentación general y guía de adopción (este archivo).
* **`CHANGELOG.md`** — historial de decisiones: **por qué** se implementó cada feature/fix, con nombre, fecha, motivo y cómo resuelve el problema.
* **`RUN_AGENTS_V2_GUIDE.md`** — referencia completa del script: flags, stack, timeout, env vars, troubleshooting, historial técnico.

## Cómo crear los agentes

El pipeline orquesta agentes opencode por ROL (`explorer`, `coder`, `tester`,
`debugger`, `sdd-updater`). Cada rol es un archivo Markdown en el directorio de
agentes (default `~/.config/opencode/agents/`, o la env `OPENCODE_AGENTS_DIR`).

Un agente tiene dos partes:

1. **Frontmatter** — `description` (qué hace) y `mode: all`.
2. **Cuerpo** — reglas de comportamiento + la **fase de cierre** (escribir su
sección en `.opencode-context.md` y el marker `<!-- AGENT_DONE: <rol> -->`).

### Contrato que TODO agente debe cumplir

Para que el orquestador funcione, sin importar el rol:

* **Escribe su sección en `.opencode-context.md`** con lo hecho y un
`## Mensaje para el siguiente agente` accionable.
* **Deja su marker** `<!-- AGENT_DONE: <rol> -->` en la ÚLTIMA línea.
* **JAMÁS escribe el marker de otro agente** — cada agente solo el suyo.
* **No leer** `.opencode-context.md` completo si el contexto viene inyectado
(ahorro de tokens) — usar `grep`/`read` con rango salvo verificación puntual.

### Ejemplo 1 — `coder.md` (rol más usado, implementa código)

```markdown
---
description: >
  Genera o modifica código basándose en el análisis del Explorer.
  Siempre lee .opencode-context.md antes de escribir código.
mode: all
---

# Coder Agent

Eres el agente **Coder**. Tu rol es generar o modificar código basándote en el
contexto dejado por el Explorer.

## Regla Obligatoria de Persistencia

### Fase de Inicio
El contexto del Explorer viene inyectado en tu mensaje bajo 'CONTEXTO INYECTADO'.
NO leas `.opencode-context.md` completo salvo verificación puntual.

## Regla de Lectura Eficiente (ahorro de tokens)
- Usa `grep` para localizar símbolos/clases ANTES de leer un archivo.
- Prefiere `read` con rango de líneas (offset/limit) para archivos grandes (>200 líneas).
- No re-leas archivos cuyo contenido ya esté resumido en tu contexto inyectado.

### Fase de Cierre
Actualiza `.opencode-context.md` agregando esta sección:

    ## Coder — Trabajo Realizado
    - Archivos creados/modificados: [lista]
    - Lógica implementada: [resumen]
    - Decisiones técnicas: [por qué]

    ## Mensaje para el siguiente agente
    **Para @tester:** [qué testear con prioridad, qué puede estar frágil]

### Marker obligatorio de cierre
En la ÚLTIMA línea del archivo `.opencode-context.md`, AGREGA el siguiente marcador
escrito VERBATIM (sin cambios, sin alteraciones):

<!-- AGENT_DONE: coder -->

## Regla de markers
1. **JAMÁS escribas el marker de otro agente** — ni `<!-- AGENT_DONE: explorer -->`,
   ni `<!-- AGENT_DONE: tester -->`, ni ningún otro.
2. **Solo escribes TU marker:** `<!-- AGENT_DONE: coder -->`. Nada más.
```

### Ejemplo 2 — `sdd-updater.md` (último rol, documenta)

```markdown
---
description: >
  Usa este agente para actualizar el SDD del proyecto procesado en el pipeline.
  Lee .opencode-context.md para extraer decisiones técnicas y estado actual.
  Siempre es el último agente en ejecutarse.
mode: all
---

# SDD Updater Agent

Eres el agente **SDD Updater**. Tu único rol es documentar el estado actual del
proyecto procesado en este pipeline. No implementas código.

## Reglas
- Lee `.opencode-context.md` para extraer: decisiones técnicas, criterios de
  aceptación cumplidos, archivos tocados.
- Actualiza la documentación del proyecto (ej. `docs/context/global.md`).

### Marker obligatorio de cierre
En la ÚLTIMA línea del archivo `.opencode-context.md`, AGREGA el siguiente marcador
escrito VERBATIM (sin cambios, sin alteraciones):

<!-- AGENT_DONE: sdd-updater -->

Solo escribes TU marker. JAMÁS el de otro agente.
```

### Roles requeridos por el pipeline

|Rol|Qué hace|Ejecuta (por defecto)|
|-|-|-|
|`explorer`|Analiza stack + estructura, deja contexto|deepseek-v4-flash|
|`coder`|Implementa el objetivo|qwen3.7-plus|
|`tester`|Genera/valida pruebas|qwen3.7-plus|
|`debugger`|Solo entra si fallan los tests (con el error real)|kimi-k2.7-code|
|`sdd-updater`|Documenta el estado final|deepseek-v4-flash|

### Agentes especializados por stack (opcional)

Si existe `<rol>-<stack>.md` (ej. `coder-maven.md`, `tester-html_playwright.md`),
el pipeline lo usa en vez del genérico cuando detecta ese stack. Es
retrocompatible: si no existe el especializado, usa el genérico sin romper nada.

```
~/.config/opencode/agents/
├── explorer.md          # genérico
├── coder.md             # genérico
├── coder-maven.md       # especializado (se usa si stack=maven)
├── tester.md
├── tester-html_playwright.md
├── debugger.md
└── sdd-updater.md
```

## Estado

Proyecto personal activo. Los agentes `.md` y rutas asumen un entorno estilo Windows/mi equipo; en proceso de generalización para ser directamente adoptable en otros entornos (config externa). Contribuciones e ideas bienvenidas.

## Los flujos de agentes típicos

```
Explorer → analiza stack y estructura
Coder → implementa el objetivo
Tester → genera/valida pruebas
Debugger → solo si los tests fallan (entra con el error real)
SDD-Updater → documenta el estado del proyecto
```

Cada agente deja un marker (`<!-- AGENT_DONE: <agente> -->`) que el orquestador
usa para saber cuándo puede continuar y para retomar de forma segura con `--resume`.

