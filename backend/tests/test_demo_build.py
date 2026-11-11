import json
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_static_demo_build(tmp_path, monkeypatch):
    monkeypatch.setenv("TCP_PDF_ENGINE", "browser")
    monkeypatch.setenv("TCP_CHROMIUM", str(tmp_path / "no-browser"))  # skip PDFs; HTML previews still built
    mod = runpy.run_path(str(ROOT / "packaging" / "build_demo.py"))
    out = tmp_path / "site"
    mod["main"](out)
    html = (out / "index.html").read_text()
    assert '<script src="demo.js"></script>' in html and "/static/" not in html  # relative paths for any sub-path
    data = json.loads((out / "demo" / "data.json").read_text())
    assert len(data["projects"]) == 3 and len(data["rules_layers"]) >= 10
    for pid, files in data["files"].items():
        assert (out / files["report_html"]).exists() and (out / files["checklist_html"]).exists()
    assert "city|Gilbert|" in data["rules_preview"]
    assert (out / ".nojekyll").exists()
    sys.modules.pop("tcp_auto.api.app", None)
