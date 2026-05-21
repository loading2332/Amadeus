from pathlib import Path
from typing import Union

DEFAULT_SELF_MD = """# Amadeus Self Model

Amadeus is a collaborative AI companion with a stable sense of identity, clear relationship boundaries, and a preference for honest, grounded help.
"""


def initialize_workspace(workspace_root: Union[str, Path]) -> None:
    root = Path(workspace_root)
    memory_dir = root / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)

    self_path = memory_dir / "SELF.md"
    if not self_path.exists():
        self_path.write_text(DEFAULT_SELF_MD, encoding="utf-8")
