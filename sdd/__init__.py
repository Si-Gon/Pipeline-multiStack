"""SDD Builder Propio — módulo del pipeline (reemplaza al MCP externo previo).

Builder mínimo integrado nativamente en el pipeline, sin servidor, sin multistack,
sin templates de scaffolding. Tres responsabilidades:

- gate.py      : estado aprobada/consentida por spec + LOCK (gate open/blocked).
- rubric.py    : score determinista de una spec (max 89, port de sdd-spec-scoring).
- spec_format.py: leer las specs NNN-slug/ de forma mínima (sin templates redundantes).

La UI (pipeline-ui) lee este mismo estado vía el bridge; ya no hay MCP externo.
Design: C:\\WorkSpace\\pipeline-ui\\DESIGN.md
"""