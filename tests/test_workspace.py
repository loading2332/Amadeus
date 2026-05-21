from amadeus.workspace import DEFAULT_SELF_MD, initialize_workspace


def test_initialize_workspace_creates_default_self_md(tmp_path):
    initialize_workspace(tmp_path)

    self_path = tmp_path / "memory" / "SELF.md"
    assert self_path.exists()
    assert self_path.read_text(encoding="utf-8") == DEFAULT_SELF_MD


def test_initialize_workspace_does_not_overwrite_existing_self_md(tmp_path):
    self_path = tmp_path / "memory" / "SELF.md"
    self_path.parent.mkdir()
    self_path.write_text("custom self model", encoding="utf-8")

    initialize_workspace(tmp_path)

    assert self_path.read_text(encoding="utf-8") == "custom self model"
