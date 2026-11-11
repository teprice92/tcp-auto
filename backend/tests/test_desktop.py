import socket

from tcp_auto import launcher
from tcp_auto.report import pdf


def test_version_flag(capsys):
    assert launcher.main(["--version"]) == 0
    assert "FlagPole" in capsys.readouterr().out


def test_pick_port_skips_busy_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        busy = s.getsockname()[1]
        assert launcher.pick_port("127.0.0.1", busy) != busy


def test_default_data_dir_is_per_user(monkeypatch):
    monkeypatch.setattr(launcher.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", r"C:\Users\me\AppData\Roaming")
    assert str(launcher.default_data_dir()).endswith("FlagPole")
    monkeypatch.setattr(launcher.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", "/home/me/.local/share")
    assert str(launcher.default_data_dir()) == "/home/me/.local/share/flagpole"


def test_tcp_chromium_override(tmp_path, monkeypatch):
    fake = tmp_path / "msedge.exe"
    fake.write_text("")
    monkeypatch.setenv("TCP_CHROMIUM", str(fake))
    assert pdf.find_browser() == str(fake)


def test_browser_pdf_engine(make_project, monkeypatch):
    """The packaged build's PDF path (installed browser, no Playwright)."""
    import pytest

    if not pdf.find_browser():
        pytest.skip("no Chromium-family browser on this machine")
    from tcp_auto.pipeline import build_plan
    from tcp_auto.report.render import render_checklist_pdf

    monkeypatch.setenv("TCP_PDF_ENGINE", "browser")
    p = make_project()
    p.plan, _, _ = build_plan(p)
    assert render_checklist_pdf(p).startswith(b"%PDF")
