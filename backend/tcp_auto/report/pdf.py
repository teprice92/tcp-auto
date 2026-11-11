"""HTML -> PDF.

Two engines, tried in order:
1. Playwright (when installed with its browser, e.g. running from source or in Docker).
2. An installed Chromium-family browser in headless print mode (Microsoft Edge ships with
   Windows; Chrome/Chromium on Linux/macOS). The packaged desktop build uses this, so it
   doesn't need to bundle a browser.

Override the browser with ``TCP_CHROMIUM=/path/to/chrome-or-msedge``.
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


class PdfUnavailable(RuntimeError):
    pass


def _candidates() -> list[str]:
    env = os.environ.get("TCP_CHROMIUM")
    out = [env] if env else []
    if sys.platform.startswith("win"):
        roots = [os.environ.get(k, "") for k in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA")]
        for r in filter(None, roots):
            out += [
                os.path.join(r, "Microsoft", "Edge", "Application", "msedge.exe"),
                os.path.join(r, "Google", "Chrome", "Application", "chrome.exe"),
                os.path.join(r, "Chromium", "Application", "chrome.exe"),
            ]
    elif sys.platform == "darwin":
        out += [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge", "microsoft-edge-stable", "msedge", "chrome"):
        if (p := shutil.which(name)):
            out.append(p)
    # Playwright-installed builds (headless shell first: it's made for printing)
    pw = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or ("/opt/pw-browsers" if os.path.isdir("/opt/pw-browsers") else
                                                         os.path.join(os.path.expanduser("~"), ".cache", "ms-playwright"))
    out += sorted(glob.glob(os.path.join(pw, "chromium_headless_shell-*", "chrome-*", "chrome-headless-shell*")))
    out += sorted(glob.glob(os.path.join(pw, "chromium-*", "chrome-*", "chrome")))
    seen, uniq = set(), []
    for c in out:
        if c and c not in seen and os.path.exists(c):
            seen.add(c)
            uniq.append(c)
    return uniq


def find_browser() -> str | None:
    c = _candidates()
    return c[0] if c else None


def _playwright_pdf(html: str, landscape: bool) -> bytes:
    from playwright.sync_api import sync_playwright  # optional dependency

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception:
            exe = find_browser()
            if not exe:
                raise
            browser = p.chromium.launch(executable_path=exe, args=["--no-sandbox"])
        try:
            page = browser.new_page()
            page.set_content(html, wait_until="load")
            return page.pdf(format="Letter", landscape=landscape, print_background=True, prefer_css_page_size=True)
        finally:
            browser.close()


def _cli_pdf(html: str) -> bytes:
    browsers = _candidates()
    if os.environ.get("TCP_CHROMIUM"):
        browsers = browsers[:1]
    else:  # headless-shell builds first: they're made for printing
        browsers = sorted(browsers, key=lambda b: "headless-shell" not in os.path.basename(b))
    if not browsers:
        raise PdfUnavailable(
            "No browser found for PDF export. Install Microsoft Edge or Google Chrome, set TCP_CHROMIUM to the "
            "browser's path, or use Preview and your browser's Print > Save as PDF."
        )
    errors = []
    for exe in browsers[:3]:
        try:
            return _print_with(exe, html)
        except PdfUnavailable as e:
            errors.append(str(e))
    raise PdfUnavailable(errors[0])


def _print_with(exe: str, html: str, timeout: float = 45) -> bytes:
    with tempfile.TemporaryDirectory(prefix="flagpole-pdf-") as tmp:
        src = Path(tmp) / "page.html"
        out = Path(tmp) / "page.pdf"
        src.write_text(html, encoding="utf-8")
        headless = "--headless" if "headless-shell" in os.path.basename(exe) else "--headless=new"
        args = [
            exe, headless, "--disable-gpu", "--no-first-run", "--no-default-browser-check", "--disable-extensions",
            "--disable-background-networking", "--disable-component-update", "--disable-dev-shm-usage",
            "--no-pdf-header-footer", "--print-to-pdf-no-header", f"--user-data-dir={Path(tmp) / 'profile'}",
            f"--print-to-pdf={out}", src.as_uri(),
        ]
        if not sys.platform.startswith("win") and hasattr(os, "geteuid") and os.geteuid() == 0:
            args.insert(1, "--no-sandbox")  # Chromium refuses to run as root without this
        proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        # Some browsers keep running after writing the file, so watch for a finished PDF.
        deadline, last = time.monotonic() + timeout, -1
        try:
            while time.monotonic() < deadline:
                size = out.stat().st_size if out.exists() else 0
                if size and size == last and out.read_bytes()[-1024:].rstrip().endswith(b"%%EOF"):
                    break
                if proc.poll() is not None and not size:
                    break
                last = size
                time.sleep(0.4)
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
        if not out.exists() or out.stat().st_size == 0:
            raise PdfUnavailable(
                f"The browser at {exe} didn't produce a PDF. Use Preview and your browser's Print > Save as PDF, "
                "or set TCP_CHROMIUM to another Chrome/Edge."
            )
        return out.read_bytes()


def html_to_pdf(html: str, landscape: bool = True) -> bytes:
    """Page size/orientation come from the template's CSS @page rule; ``landscape`` is a hint for Playwright."""
    if os.environ.get("TCP_PDF_ENGINE", "auto") != "browser":
        try:
            return _playwright_pdf(html, landscape)
        except ImportError:
            pass  # packaged build: no Playwright
        except Exception:
            pass  # Playwright installed but no usable browser: fall back
    return _cli_pdf(html)
