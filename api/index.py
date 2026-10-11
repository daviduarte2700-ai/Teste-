"""Ponto de entrada da Vercel: expõe o app FastAPI de src/hashtag_motoboys."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from hashtag_motoboys.app import app  # noqa: E402,F401
