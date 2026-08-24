# CHANGELOG — run_agents_v2.py

Registro centralizado de **por qué** se implementó cada feature/fix. Para entender
el qué/cómo técnico, ve el `RUN_AGENTS_V2_GUIDE.md` (uso) o el `README.md`
(presentación general). Este archivo es el **historial de decisiones**.

Formato de cada entrada: **nombre · fecha · por qué se pensó · cómo lo resuelve**.

## Tabla de cambios

| Nombre | Fecha | Por qué se pensó | Cómo lo arregla |
|---|---|---|---|
| **Marker canónico** `<!-- AGENT_DONE: <rol> -->` | 2026-07-25 | v1 se "quedaba en el aire" al final del Coder: el orquestador no podía saber con certeza si un agente terminó | Cada agente deja un marker HTML-comment en la última línea de `.opencode-context.md`; combinado con `returncode==0` da detección de fin robusta + reintento limpio |
| **Stack auto-detect** | 2026-07-25 | v1 tenía stacks hardcodeados; un pipeline agnóstico debía funcionar en Maven, pytest, npm, go, dotnet, frontend | `detect_stack()` infiere el runner del proyecto y la validación correspondiente (tests / Playwright headless) |
| **Bucle Coder→Tester→Debugger con guard** | 2026-07-25 | El Debugger no debía lanzarse sin un error real; proyectos sin runner daban "false success" | Solo se invoca Debugger si hay `error_log` no vacío Y un runner detectado; si no, nota de validación manual |
| **Backup ALWAYS de contexto** | 2026-07-25 | El `.opencode-context.md` se podía pisar sin copia | Respalda el contexto a `pipeline-artifacts/context-history/` antes de cada corrida |
| **Log persistente por pipeline** | 2026-07-25 | No quedaba rastro de qué pasó en cada corrida | Log con timestamp + agente + snippet de errores en `pipeline-artifacts/pipeline-<ts>.log` |
| **Objetivo primero / contexto inyectado** | 2026-07-25 | El objetivo del usuario se mezclaba con el contexto previo | El bloque `=== OBJETIVO DEL USUARIO ===` va separado; el contexto previo es una sección aparte |
| **`--objective-file`** | 2026-08-07 | Abes largas/specs con caracteres especiales rompían el quoting de argv (WinError 206) | Se lee el objetivo desde archivo byte-for-byte, o stdin con `-` |
| **Timeout por agente + override env** | 2026-08-07 | El Coder superaba el timeout global (20min) en proyectos medianos | Timeouts por agente (coder=40min default) + override `OC_AGENT_TIMEOUT_<AGENTE>` |
| **`--mcp-minimal` / `--no-mcp-minimal`** | 2026-08-07 | Los tool-schemas de MCP globales se inyectaban en CADA request (miles de tokens); la mayor fuga de costos | Deshabilita MCP globales por proyecto en `.opencode/opencode.json`, respetando decisiones explícitas |
| **WinError 206 — objetivo a archivo temporal** | 2026-08-07 | Windows limita argv a ~32K chars; el objetivo (spec+contexto) lo excedía | Se escribe el objetivo completo a un archivo en `pipeline-artifacts/` y se adjunta con `opencode run -f` |
| **Caché persistente de Playwright** | 2026-08-07 | Antes se descargaba Playwright en cada corrida (30s-6min extra) | Caché reutilizable en `~/.opencode/playwright-cache/` |
| **Budget de contexto `--budget-inject`** | 2026-08-23 | El contexto inyectado podía crecer sin control y disparar la factura de tokens | Presupuesto por agente (default 9000 tok): recorta el contexto inyectado de forma priorizada si lo excede (conserva el bloque del agente anterior, resume los viejos) |
| **Reporte de costo estimado** | 2026-08-23 | No había forma de saber cuánto costaba cada corrida en USD | Factura estimada por modelo (entrada/salida) al final, con precios de `MODEL_PRICING` |
| **Exit codes por fase + `pipeline-status.json`** | 2026-08-23 | A abortar con `sys.exit(1)` no se sabía qué fase falló; el resume era a ciegas | Cada fase falla con exit code distinto (2-6) y escribe `pipeline-status.json` con el último paso + fase fallida, para relanzar directo |
| **Aviso de fallo de SDD-updater** | 2026-08-23 | SDD-updater no abortaba, pero si fallaba QUIETO quedaba el SDD desactualizado sin que nadie lo supiera | Se captura su resultado: avisa en consola + lo refleja en `pipeline-status.json` (sin marcar el pipeline como fallido) |
| **Re-detección de stack tras Coder** | 2026-08-23 | El stack se detectaba UNA vez al inicio; si el Coder cambiaba el runner (nuevo package.json/pom.xml/wrapper), el Tester/debug usaba el stack viejo | Re-llama `detect_stack()` antes del bucle Tester→Debugger, para ejecutar/verificar tests con el runner correcto |
| **Limpieza de referencias personales** | 2026-08-23 | El script tenía rutas hardcodeadas (`C:\Users\Silvi\...`), nombres de proyectos propios y códigos internos (PAUD-xxx, P10/P11) que un tercero no entendería | Rutas dinámicas con `os.path.expanduser("~")`; referencias genéricas; cada comentario se reescribió para explicarse solo |