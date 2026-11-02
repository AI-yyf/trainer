from pathlib import Path

from app.evaluator.service import _copy_project_to_sandbox


def test_project_copy_includes_tests_and_skips_tool_caches(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    (project / "src" / "queue_lock.py").write_text("import threading\n", encoding="utf-8")
    (project / "test_queue_lock.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )
    (project / ".venv").mkdir()
    (project / ".venv" / "huge.bin").write_text("x", encoding="utf-8")
    (project / "__pycache__").mkdir()
    (project / "__pycache__" / "stale.pyc").write_text("x", encoding="utf-8")
    (project / "linked.py").symlink_to(project / "src" / "queue_lock.py")

    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()

    assert _copy_project_to_sandbox(project, sandbox) is True
    assert (sandbox / "src" / "queue_lock.py").read_text(encoding="utf-8") == "import threading\n"
    assert (sandbox / "test_queue_lock.py").exists()
    assert not (sandbox / ".venv").exists()
    assert not (sandbox / "__pycache__").exists()
    assert not (sandbox / "linked.py").exists()


def test_missing_project_root_cannot_be_copied(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    assert _copy_project_to_sandbox(tmp_path / "missing", sandbox) is False


def test_project_copy_skips_non_regular_files(tmp_path: Path) -> None:
    import os

    project = tmp_path / "project"
    project.mkdir()
    (project / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    fifo = project / "pipe"
    try:
        os.mkfifo(fifo)
    except (AttributeError, OSError):
        return
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()

    assert _copy_project_to_sandbox(project, sandbox) is True
    assert (sandbox / "test_ok.py").exists()
    assert not (sandbox / "pipe").exists()
