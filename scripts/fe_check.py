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

# 8) R3 invariants: new shared modules exist
R3_MODULES = ["router", "cache", "tasks", "validators", "contracts", "a11y"]
for mod in R3_MODULES:
    p = ROOT / "js" / "shared" / f"{mod}.js"
    if not p.exists():
        errors.append(f"R3 module missing: shared/{mod}.js")

def js(path):
    p = ROOT / path
    return p.read_text(encoding="utf-8") if p.exists() else ""

# 9) router wired into view.initNav (hash routing active)
view = js("js/shared/view.js")
if "onRouteChange" not in view or "parseHash" not in view:
    errors.append("view.js initNav not wired to router (onRouteChange/parseHash missing)")

# 10) validators wired into the three submit sites
if "validateConsultationPayload" not in js("js/patient.js"):
    errors.append("patient.js: consultation submit not guarded by validateConsultationPayload")
if "validateReviewPayload" not in js("js/doctor.js"):
    errors.append("doctor.js: review submit not guarded by validateReviewPayload")
adm = js("js/admin.js")
if "validateKnowledgeDocument" not in adm:
    errors.append("admin.js: knowledge create not guarded by validateKnowledgeDocument")
if "validateWorkflowGraph" not in adm:
    errors.append("admin.js: workflow save not guarded by validateWorkflowGraph")

# 11) a11y wired into modal (components) and drawer (view)
comp = js("js/shared/components.js")
if "trapFocus" not in comp or "restoreFocus" not in comp:
    errors.append("components.openModal not wired to a11y (trapFocus/restoreFocus)")
if "trapFocus" not in view or "restoreFocus" not in view:
    errors.append("view.openDrawer not wired to a11y (trapFocus/restoreFocus)")

# 12) workflow graph renderer present
if "renderWorkflowGraph" not in adm:
    errors.append("admin.js: renderWorkflowGraph missing")

# 13) concurrency guard on doctor report
if "runLatest" not in js("js/doctor.js"):
    warnings.append("doctor.js: loadDoctorReport not wrapped in runLatest")

# 14) form.js exists and is used by the three submit pages
if not (ROOT / "js" / "shared" / "form.js").exists():
    errors.append("shared/form.js missing")
for page in ["patient.js", "doctor.js", "admin.js"]:
    src = js(f"js/{page}")
    if "applyErrors" not in src or "clearFormErrors" not in src:
        errors.append(f"{page}: not wired to form.js (applyErrors/clearFormErrors)")

# 15) validators expose the new field-level functions
val = js("js/shared/validators.js")
for fn in ["validateTreatmentRecord", "validateReminder", "validateToothRecord", "validateProfile"]:
    if f"export function {fn}" not in val:
        errors.append(f"validators.js missing {fn}")
if "fieldErrors" not in val:
    errors.append("validators.js: fieldErrors not returned")

# 16) api.js converts 422 to a friendly message
if "422" not in js("js/shared/api.js"):
    errors.append("api.js: no 422 handling (raw Pydantic JSON would leak)")

print("\n=== RESULT ===")
for w in warnings: print("WARN:", w)
for e in errors: print("ERROR:", e)
print(f"\n{len(errors)} errors, {len(warnings)} warnings")
sys.exit(1 if errors else 0)
