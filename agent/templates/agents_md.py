from pathlib import Path

_AGENTS_MD_PATH = Path(__file__).resolve().parent.parent.parent / ".agents" / "AGENTS.md"

AGENTS_MD = _AGENTS_MD_PATH.read_text()
