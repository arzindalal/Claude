# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for ISO 26262 Validation Tool.

Build (from the repo root on Windows):
    pip install pyinstaller
    pyinstaller ISO26262Validator.spec --clean

Output: dist\ISO26262Validator\ISO26262Validator.exe  (plus supporting files)
Then compile installer\setup.iss with Inno Setup 6 to produce the installer.
"""

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

block_cipher = None

# ── Collect the application package (uvicorn.run string import won't be seen by PyInstaller) ──
iso_hidden = collect_submodules("iso26262_validator")

# ── Collect packages that use dynamic/plugin loading ──────────────────────────

chroma_datas,    chroma_bins,    chroma_hidden    = collect_all("chromadb")
st_datas,        st_bins,        st_hidden        = collect_all("sentence_transformers")
tokenizers_d,    tokenizers_b,   tokenizers_h     = collect_all("tokenizers")
hugging_d,       hugging_b,      hugging_h        = collect_all("huggingface_hub")
torch_datas,     torch_bins,     torch_hidden     = collect_all("torch")
numpy_datas,     numpy_bins,     numpy_hidden     = collect_all("numpy")
scipy_datas,     scipy_bins,     scipy_hidden     = collect_all("scipy")

# ── Application data files ─────────────────────────────────────────────────────

app_datas = [
    (
        "iso26262_validator/ui/templates",
        "iso26262_validator/ui/templates",
    ),
    (
        "iso26262_validator/sample_data",
        "iso26262_validator/sample_data",
    ),
]

all_datas = (
    app_datas
    + chroma_datas
    + st_datas
    + tokenizers_d
    + hugging_d
    + torch_datas
    + numpy_datas
    + scipy_datas
)

all_binaries = (
    chroma_bins
    + st_bins
    + tokenizers_b
    + hugging_b
    + torch_bins
    + numpy_bins
    + scipy_bins
)

all_hidden = (
    iso_hidden
    + chroma_hidden
    + st_hidden
    + tokenizers_h
    + hugging_h
    + torch_hidden
    + numpy_hidden
    + scipy_hidden
    + [
        # uvicorn dynamic protocol/loop selection
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.loops.asyncio",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        # FastAPI / Starlette internals
        "fastapi",
        "fastapi.middleware",
        "starlette.routing",
        "starlette.middleware.base",
        # SQLAlchemy dialects
        "sqlalchemy.dialects.sqlite",
        "sqlalchemy.dialects.sqlite.pysqlite",
        # async transport
        "anyio._backends._asyncio",
        "anyio._backends._trio",
        "httptools",
        "websockets",
        "websockets.legacy",
        # file parsing
        "openpyxl",
        "pandas",
        "pdfplumber",
        "docx",
        # multipart upload
        "multipart",
        "python_multipart",
        # misc
        "aiofiles",
        "anthropic",
        "typer",
        "click",
    ]
)

# ── Analysis ───────────────────────────────────────────────────────────────────

a = Analysis(
    ["launcher.py"],
    pathex=[],
    binaries=all_binaries,
    datas=all_datas,
    hiddenimports=all_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib",
        "IPython",
        "jupyter",
        "notebook",
        "tkinter",
        "PyQt5",
        "PyQt6",
        "wx",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ── Executable ─────────────────────────────────────────────────────────────────

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ISO26262Validator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,       # keeps the terminal window so users see startup logs
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon="installer\icon.ico",   # uncomment if you add an icon file
)

# ── Collect (--onedir output) ──────────────────────────────────────────────────

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=["vcruntime140.dll", "python*.dll"],
    name="ISO26262Validator",
)
