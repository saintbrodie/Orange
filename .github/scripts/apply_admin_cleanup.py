from pathlib import Path

admin = Path("static/admin.html")
text = admin.read_text(encoding="utf-8")

start = text.find('                    <div class="pt-4 border-t border-zinc-800/50">\n                        <h3 class="text-sm font-semibold text-zinc-300 mb-4">Workflow Management</h3>')
if start == -1:
    raise SystemExit("Could not find legacy Workflow Management block")
end_marker = '                    </div>\n'
end = text.find(end_marker, start)
if end == -1:
    raise SystemExit("Could not find end of legacy Workflow Management block")
# The first closing div is the inner flex container; include the outer closing div too.
end = text.find(end_marker, end + len(end_marker))
if end == -1:
    raise SystemExit("Could not find outer end of legacy Workflow Management block")
end += len(end_marker)
text = text[:start] + text[end:]

text = text.replace(
    '<i data-lucide="wrench" class="w-4 h-4"></i> Tool Editor',
    '<i data-lucide="wrench" class="w-4 h-4"></i> Tools',
    1,
)

admin_script = '    <script src="/static/admin.js?v=6"></script>'
library_script = '    <script src="/static/workflow-pack-library.js?v=3"></script>'
if library_script not in text:
    if admin_script not in text:
        raise SystemExit("Could not find Admin script insertion point")
    text = text.replace(admin_script, admin_script + "\n" + library_script, 1)

admin.write_text(text, encoding="utf-8")

docs = Path("docs/WORKFLOW_PACKS.md")
docs_text = docs.read_text(encoding="utf-8")
docs_text = docs_text.replace(
    "Use **Admin → General Settings → Curated Tools**.",
    "Use **Admin → Tools → Curated Library**.",
)
docs.write_text(docs_text, encoding="utf-8")
