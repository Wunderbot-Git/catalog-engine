import json
from pathlib import Path

_DIR = Path(__file__).parent

SYSTEM_PROMPT: str = (_DIR / "system.txt").read_text().strip()

FEW_SHOT_EXAMPLES: list[dict] = json.loads((_DIR / "few_shot.json").read_text())
