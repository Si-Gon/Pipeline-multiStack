"""visual_anchors.py — diff estructural maqueta→producto (mejora E2E, Opción B).

NO compara píxeles y NO usa una checklist de clases de una maqueta concreta
(no se repetirían entre maquetas). La base son **tags semánticos estándar de HTML** —
la estructura que toda maqueta y todo producto deberían compartir por defecto:
header/nav/main/aside/footer/article/section/form + roles interactivos.

De cada maqueta se EXTRAEN los que realmente usa (emisión adaptativa): solo se
verifican en el producto los tags que la maqueta declara. Así es reutilizable entre
maquetas distintas (natación, catalog, lo que venga) sin editar el código.

Por qué NO pixel-diff: la maqueta es estática y el producto dinámico (datos que
cambian en producción) → comparar píxeles da falsos negativos. La ESTRUCTURA
semántica persiste aunque cambien los datos.
"""

import re

# Tags semánticos estándar de HTML5 (los "por defecto" que toda maqueta usa).
# Pluralizamos al selector: nav → nav; input[type=search], button, etc.
STANDARD_TAGS = [
    "header", "main", "nav", "aside", "footer", "article", "section",
    "form", "button", "input", "select", "textarea", "table", "ul", "ol",
    "img", "a", "h1", "h2", "h3", "label",
]

# En el producto, los controles de formulario se exigen como selectores de rol
# (por si el navegador/JS los transforma). Tags que exigimos como elemento vivo.
INTERACTIVE_ROLES = [
    "button", "input[type=\"search\"]", "select", "a",
]


def _extract_present_tags(html: str) -> set:
    """Devuelve los tags semánticos estándar que APARECEN en el HTML."""
    present = set()
    # tags en minúsculas (asumimos HTML bien formado; entre <tag ...> o </tag>)
    for tag in STANDARD_TAGS:
        # etiqueta de apertura <tag ...> o de cierre </tag>
        if re.search(r"<" + re.escape(tag) + r"[\s>/]", html, re.I):
            present.add(tag)
    return present


def extract_anchors(maqueta_html: str) -> dict:
    """Extrae las anclas (tags semánticos) que la maqueta realmente usa.

    Devuelve {'structural': [selector,...], 'total': N}. Los selectores son tags
    estándar; en el producto se evalúan con document.querySelector(tag).
    """
    present = _extract_present_tags(maqueta_html)

    structural = []
    # tags de estructura en orden típico (para estabilidad del reporte)
    order = ["header", "nav", "aside", "main", "section", "article", "footer",
             "form", "button", "input", "select", "table", "ul", "ol", "img",
             "a", "h1", "h2", "h3", "label"]
    for tag in order:
        if tag in present:
            structural.append(tag)

    return {"structural": sorted(structural), "total": len(structural)}


def build_check_script(anchors: list, out_file: str, shot_file: str) -> str:
    """Genera el JS (.cjs) que Playwright ejecuta: verifica cada ancla en el DOM
    del producto + toma screenshot. Devuelve el código del script."""
    anchors_json = json_dumps(anchors)
    return f"""
    const {{ chromium }} = require('playwright');
    const fs = require('fs');
    const anchors = {anchors_json};
    (async () => {{
        const browser = await chromium.launch({{ headless: true }});
        const page = await browser.newPage({{ viewport: {{ width: 1280, height: 900 }} }});
        const results = [];
        try {{
            await page.goto(process.argv[2], {{ waitUntil: 'load', timeout: 30000 }});
            await page.waitForTimeout(2500);
            for (const sel of anchors) {{
                const found = await page.evaluate((s) => {{
                    const el = document.querySelector(s);
                    return el ? {{
                        found: true,
                        count: document.querySelectorAll(s).length,
                        visible: !!(el.offsetParent ||
                                   (el.getClientRects && el.getClientRects().length))
                    }} : {{ found: false, count: 0, visible: false }};
                }}, sel);
                results.push({{ selector: sel, ...found }});
            }}
            await page.screenshot({{ path: process.argv[4], fullPage: true }});
        }} catch (e) {{
            results.push({{ selector: '__nav__', found: false, count: 0, visible: false, error: e.message }});
        }}
        const found = results.filter(r => r.found).length;
        const total = anchors.length;
        fs.writeFileSync(process.argv[3], JSON.stringify({{ results, found, total,
            coverage: total ? Math.round(100 * found / total) : 0 }}, null, 2));
        await browser.close();
    }})().catch(e => {{ console.error('HARNESS: ' + e.message); process.exit(2); }});
    """


def json_dumps(obj) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False)