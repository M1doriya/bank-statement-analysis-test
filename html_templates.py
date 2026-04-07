from pathlib import Path
from typing import Dict

_TEMPLATE_DIR = Path(__file__).resolve().parent / "template" / "fragments"
_CACHE: Dict[str, str] = {}


def render_fragment(name: str, **context: str) -> str:
    if name not in _CACHE:
        _CACHE[name] = (_TEMPLATE_DIR / name).read_text(encoding="utf-8")

    rendered = _CACHE[name]
    for key, value in context.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", value)
    return rendered
