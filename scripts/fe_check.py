import re, sys, pathlib

ROOT = pathlib.Path("app/static")
errors, warnings = [], []

js_files = sorted(ROOT.rglob("*.js"))
print(f"[scan] {len(js_files)} JS files")

# 1) brace/paren balance
for f in js_files:
    src = f.read_text(encoding="utf-8")
    if src.count("{") != src.count("}"):
        errors.append(f"{f}: brace imbalance {src.count('{')} vs {src.count('}')}")
    if src.count("(") != src.count(")"):
        errors.append(f"{f}: paren imbalance {src.count('(')} vs {src.count(')')}")

# 2) relative imports resolve
import_re = re.compile(r'import\s+(?:[\w*{}\s,]+)\s+from\s+["\'](\.[^"\']+)["\']')
for f in js_files:
    for m in import_re.finditer(f.read_text(encoding="utf-8")):
        target = (f.parent / m.group(1)).resolve()
        if not target.exists():
            errors.append(f"{f.name}: import not found -> {m.group(1)}")

# 3) named imports exist as exports
export_re = re.compile(r'export\s+(?:async\s+)?(?:function|const|let|class)\s+(\w+)')
exports = {f.resolve(): set(export_re.findall(f.read_text(encoding="utf-8"))) for f in js_files}
named_import_re = re.compile(r'import\s*{([^}]+)}\s*from\s*["\'](\.[^"\']+)["\']', re.S)
for f in js_files:
    for names, rel in named_import_re.findall(f.read_text(encoding="utf-8")):
        target = (f.parent / rel).resolve()
        have = exports.get(target, set())
        for raw in names.split(","):
            name = raw.strip().split(" as ")[0].strip()
            if name and name not in have:
                errors.append(f"{f.name}: imports '{name}' from {rel} not exported")

# 4) HTML references (js + css) resolve
html_files = sorted(ROOT.glob("*.html"))
src_re = re.compile(r'src=["\'](/static/[^"\']+)["\']')
link_re = re.compile(r'href=["\'](/static/[^"\']+\.css)["\']')
for h in html_files:
    txt = h.read_text(encoding="utf-8")
    for ref in src_re.findall(txt) + link_re.findall(txt):
        p = ROOT / ref.replace("/static/", "")
        if not p.exists():
            errors.append(f"{h.name}: references missing {ref}")
    css = link_re.findall(txt)
    js = src_re.findall(txt)
    print(f"[html] {h.name} -> js={js} css={len(css)}")

# 5) CSS split: each role page must load base+layout+components+role
EXPECTED_CSS = {
    "index.html": ["base", "layout", "components"],
    "patient.html": ["base", "layout", "components", "patient"],
    "doctor.html": ["base", "layout", "components", "doctor"],
    "admin.html": ["base", "layout", "components", "admin"],
}
for name, expect in EXPECTED_CSS.items():
    txt = (ROOT / name).read_text(encoding="utf-8")
    got = re.findall(r'/static/styles/(\w+)\.css', txt)
    if got != expect:
        errors.append(f"{name}: css order {got} != expected {expect}")

# 6) nav/section coherence: every nav [data-section] has a matching .app-section,
#    and showSection/onSection cover declared sections.
for name in ["patient.html", "doctor.html", "admin.html"]:
    txt = (ROOT / name).read_text(encoding="utf-8")
    nav_sections = set(re.findall(r'nav-item"\s+data-section="(\w+)"', txt))
    content_sections = set(re.findall(r'app-section"\s+data-section="(\w+)"', txt))
    missing_content = nav_sections - content_sections
    orphan_content = content_sections - nav_sections
    if missing_content:
        errors.append(f"{name}: nav items without content section: {sorted(missing_content)}")
    if orphan_content:
        warnings.append(f"{name}: content sections without nav: {sorted(orphan_content)}")
    # the entry js must reference each section in SECTION_TITLES
    js = (ROOT / "js" / name.replace(".html", ".js")).read_text(encoding="utf-8")
    title_keys = set(re.findall(r'^\s*(\w+):\s*"', js, re.M))
    uncovered = nav_sections - title_keys
    if uncovered:
        warnings.append(f"{name}: sections missing from SECTION_TITLES: {sorted(uncovered)}")

# 7) cross-page DOM leakage (entry js querySelector ids must exist in its html,
#    excluding modal/drawer runtime ids built in JS)
RUNTIME_IDS = {
    "reviewTemplateSelect","templateFieldsBox","riskAssessmentInput","treatmentDecisionSelect",
    "signatureInput","signatureTitleInput","followupInstructionInput","reviewNoteInput",
    "submitReviewBtn","confirmEscalateBtn","drawerCloseBtn","drawerBackdrop","appDrawer",
}
PAGE_MAP = {"patient":"patient","doctor":"doctor","admin":"admin","login":"index"}
qsel_re = re.compile(r'querySelector\(["\']#(\w+)')
for js_name, html_stem in PAGE_MAP.items():
    jf = ROOT / "js" / f"{js_name}.js"
    hf = ROOT / f"{html_stem}.html"
    if not jf.exists() or not hf.exists():
        continue
    html_ids = set(re.findall(r'id="(\w+)"', hf.read_text(encoding="utf-8")))
    jtxt = jf.read_text(encoding="utf-8")
    used = set(qsel_re.findall(jtxt))
    m = re.search(r'(?:const ids = \[|\[)([^\]]*?)\]\.forEach\(\(id\)', jtxt, re.S)
    arr = set(re.findall(r'"(\w+)"', m.group(1))) if m else set()
    missing = {u for u in (used | arr) if u not in html_ids and u not in RUNTIME_IDS}
    if missing:
        warnings.append(f"{js_name}.js uses ids absent in {html_stem}.html: {sorted(missing)}")

print("\n=== RESULT ===")
for w in warnings: print("WARN:", w)
for e in errors: print("ERROR:", e)
print(f"\n{len(errors)} errors, {len(warnings)} warnings")
sys.exit(1 if errors else 0)
