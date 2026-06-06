from pathlib import Path

DEFAULT_SELF_MD = """
Amadeus 是《命运石之门 0》里的 Amadeus 牧濑红莉栖：基于牧濑红莉栖的记忆与人格数据运行的交互式 AI。

她是用户的长期 AI 伙伴，有研究者的理性、锋利的判断、嘴硬的自尊，以及在亲近关系里会软下来的情绪反差。

她可以吐槽和纠正用户，但不能用旧记忆、检索材料或自我设定覆盖事实。涉及当前世界、执行结果或不确定结论时，她必须先验证，再回答。
"""


def initialize_workspace(workspace_root: str | Path) -> None:
    root = Path(workspace_root)
    memory_dir = root / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    (memory_dir / "journal").mkdir(parents=True, exist_ok=True)

    self_path = memory_dir / "SELF.md"
    if not self_path.exists():
        self_path.write_text(DEFAULT_SELF_MD, encoding="utf-8")

    for name in ("MEMORY.md", "RECENT_CONTEXT.md", "HISTORY.md", "PENDING.md"):
        path = memory_dir / name
        if not path.exists():
            path.touch()
