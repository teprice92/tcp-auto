# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for FlagPole.

Build (on the OS you're targeting; PyInstaller doesn't cross-compile):

    pip install -e backend pyinstaller
    pyinstaller flagpole.spec                 # folder build:  dist/FlagPole/
    FLAGPOLE_ONEFILE=1 pyinstaller flagpole.spec   # single file:  dist/FlagPole(.exe)

The folder build starts faster; zip dist/FlagPole/ to share it. The single-file build is one
file to hand out but unpacks itself on every start (a few seconds).

PDFs use the computer's Microsoft Edge or Google Chrome, so no browser is bundled.
Playwright and PyMuPDF's optional AI layout extras are excluded to keep the build small.
"""

import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ONEFILE = os.environ.get("FLAGPOLE_ONEFILE") == "1"
ROOT = os.path.abspath(SPECPATH)

datas = [
    (os.path.join(ROOT, "frontend"), "frontend"),
    (os.path.join(ROOT, "rules"), "rules"),
    (os.path.join(ROOT, "backend", "tcp_auto", "report", "templates"), os.path.join("tcp_auto", "report", "templates")),
    (os.path.join(ROOT, "backend", "tcp_auto", "extract", "keywords.yaml"), os.path.join("tcp_auto", "extract")),
]
datas += collect_data_files("anthropic")

hiddenimports = (
    collect_submodules("tcp_auto")
    + collect_submodules("uvicorn")
    + ["pymupdf", "multipart", "python_multipart", "email.mime.application", "anthropic"]
)

excludes = [
    "playwright",  # PDFs use the installed Edge/Chrome instead (see tcp_auto/report/pdf.py)
    # PyMuPDF 2.x optional AI layout/LLM extras: not used (text extraction only)
    "pymupdf.layout", "pymupdf4llm", "pymupdf_layout", "onnxruntime", "networkx", "numpy", "PIL", "tabulate",
    "tkinter", "matplotlib", "numpy.tests", "PIL.ImageQt", "PyQt5", "PySide6", "IPython", "pytest",
]

icon = os.path.join(ROOT, "packaging", "flagpole.ico") if sys.platform.startswith("win") else None

a = Analysis(
    [os.path.join(ROOT, "packaging", "flagpole_main.py")],
    pathex=[os.path.join(ROOT, "backend")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
# Drop PyMuPDF's bundled AI layout model and C headers (hooks pull them in; the app doesn't use them).
_drop = (os.path.join("pymupdf", "layout"), os.path.join("pymupdf", "mupdf-devel"))
a.datas = [d for d in a.datas if not d[0].startswith(_drop)]
a.binaries = [b for b in a.binaries if not b[0].startswith(_drop)]

pyz = PYZ(a.pure)

exe_kwargs = dict(
    name="FlagPole",
    debug=False,
    strip=False,
    upx=False,
    console=True,  # the console window shows the address and stops the app when closed
    icon=icon,
)

if ONEFILE:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], runtime_tmpdir=None, **exe_kwargs)
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **exe_kwargs)
    coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="FlagPole")
