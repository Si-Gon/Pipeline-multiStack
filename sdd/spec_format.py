"""spec_format.py — lectura mínima de specs NNN-slug/ (sin templates de scaffolding).

El builder propio NO genera templates de ejemplo (new-spec, check-*, templates/*).
Solo lee las specs como carpetas @spec/specs/NNN-slug/ con su spec.md. Las specs
se escriben a mano (o con --objective-file), no se "andalizan".
"""
import os

SPECS_DIR_REL = os.path.join("spec", "specs")


def specs_dir(project_root: str) -> str:
    return os.path.join(project_root, *SPECS_DIR_REL.split(os.sep))


def list_specs(project_root: str) -> list:
    """Lista las specs: [{id, dir, fileScope, status}]. Solo carpetas con spec.md."""
    d = specs_dir(project_root)
    out = []
    if not os.path.isdir(d):
        return out
    for entry in sorted(os.listdir(d)):
        full = os.path.join(d, entry)
        if entry.startswith("_"):
            continue
        if not os.path.isdir(full):
            continue
        if not os.path.exists(os.path.join(full, "spec.md")):
            continue
        out.append({"id": entry, "dir": full, "status": "Pendiente", "fileScope": []})
    return out


def resolve_spec_by_input(project_root: str, spec_id: str) -> dict | None:
    """Encuentra una spec por id, número o prefijo.
    Acepta: '001', '1', '001-tienda...', 'tienda', '2'. Hace match por:
    número exacto (con/sin ceros), prefijo del id, subcadena del slug."""
    specs = list_specs(project_root)
    spec_id = spec_id.strip()
    if not spec_id:
        return None
    # normaliza "1" → "001"
    if spec_id.isdigit():
        padded = spec_id.zfill(3)
        for s in specs:
            if s["id"].startswith(padded):
                return s
    for s in specs:
        if s["id"] == spec_id or s["id"].startswith(spec_id):
            return s
    # fallback: subcadena en el slug
    for s in specs:
        if spec_id.lower() in s["id"].lower():
            return s
    return None