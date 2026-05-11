"""
Windows launcher for the ISO 26262 Validation Tool.

- Stores all data (SQLite + ChromaDB) in %APPDATA%\ISO26262Validator
- Reads ANTHROPIC_API_KEY from the environment or from
  %APPDATA%\ISO26262Validator\config.env (KEY=VALUE format)
- Starts the uvicorn server on localhost:8000 and opens the browser
"""

from __future__ import annotations

import os
import sys
import threading
import time
import webbrowser
from pathlib import Path


# ── Data directory ─────────────────────────────────────────────────────────────

_APP_DATA = Path(os.environ.get("APPDATA", ".")) / "ISO26262Validator"
_APP_DATA.mkdir(parents=True, exist_ok=True)

os.environ.setdefault("KB_DB", str(_APP_DATA / "kb.sqlite"))
os.environ.setdefault("KB_CHROMA", str(_APP_DATA / "chroma"))


# ── API key ────────────────────────────────────────────────────────────────────

def _load_config_env() -> None:
    """Read KEY=VALUE pairs from config.env if ANTHROPIC_API_KEY is not set."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    config_file = _APP_DATA / "config.env"
    if not config_file.exists():
        config_file.write_text(
            "# Set your Anthropic API key here\n"
            "ANTHROPIC_API_KEY=\n"
        )
        print(
            f"\n[ISO 26262] No API key found.\n"
            f"  Open this file and paste your key:\n"
            f"  {config_file}\n"
            f"  Then restart the application.\n"
        )
        return
    for line in config_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if key and value:
                os.environ.setdefault(key, value)


_load_config_env()


# ── PyInstaller path fix ───────────────────────────────────────────────────────
# Ensure the bundled package root is on sys.path when running frozen.

if getattr(sys, "frozen", False):
    _bundle_dir = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    if str(_bundle_dir) not in sys.path:
        sys.path.insert(0, str(_bundle_dir))


# ── Server + browser ───────────────────────────────────────────────────────────

HOST = "127.0.0.1"
PORT = 8000


def _open_browser() -> None:
    time.sleep(2.5)
    webbrowser.open(f"http://{HOST}:{PORT}")


def main() -> None:
    import uvicorn

    print("=" * 60)
    print(" ISO 26262 Validation Tool")
    print(f" URL : http://{HOST}:{PORT}")
    print(f" Data: {_APP_DATA}")
    print(" Press Ctrl+C to stop.")
    print("=" * 60)

    threading.Thread(target=_open_browser, daemon=True).start()

    uvicorn.run(
        "iso26262_validator.api.app:app",
        host=HOST,
        port=PORT,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
