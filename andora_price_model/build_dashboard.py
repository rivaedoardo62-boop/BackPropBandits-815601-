"""Inietta il modello esportato dentro dashboard.html.

Idempotente: sostituisce il contenuto del tag <script id="model-data"> con il
JSON fresco (sia il placeholder __MODEL_JSON__ sia un JSON gia' iniettato).
Eseguire dopo ml_pipeline.py.
"""

import re
from pathlib import Path

HERE = Path(__file__).parent
html = (HERE / "dashboard.html").read_text()
model = (HERE / "data" / "modello_export.json").read_text()
assert "</script>" not in model, "il JSON non deve contenere </script>"

pattern = re.compile(
    r'(<script id="model-data" type="application/json">).*?(</script>)',
    re.DOTALL,
)
new_html, n = pattern.subn(lambda m: m.group(1) + model + m.group(2), html)
assert n == 1, f"tag model-data trovato {n} volte (atteso 1)"
(HERE / "dashboard.html").write_text(new_html)
print(f"dashboard.html aggiornata ({len(new_html)/1024:.0f} KB, modello {len(model)/1024:.0f} KB)")
