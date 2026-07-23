"""Inietta reports/dashboard_export.json dentro reports/dashboard.html (idempotente)."""
import re
from pathlib import Path

R = Path(__file__).resolve().parents[1] / "reports"
html = (R / "dashboard.html").read_text()
model = (R / "dashboard_export.json").read_text()
assert "</script>" not in model
pat = re.compile(r'(<script id="model-data" type="application/json">).*?(</script>)', re.DOTALL)
new, n = pat.subn(lambda m: m.group(1) + model + m.group(2), html)
assert n == 1, f"tag trovato {n} volte"
(R / "dashboard.html").write_text(new)
print(f"dashboard.html aggiornata ({len(new)/1024:.0f} KB)")
