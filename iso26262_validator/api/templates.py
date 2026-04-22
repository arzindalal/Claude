"""
Jinja2Templates instance shared across all routers.
Isolated here to break the circular import between app.py and routers/ui.py.
"""

from pathlib import Path

from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(
    directory=str(Path(__file__).parent.parent / "ui" / "templates")
)
