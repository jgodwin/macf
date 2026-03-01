import pytest
import tempfile
from pathlib import Path
from macf.file_manager import FileManager


@pytest.fixture
def fm(tmp_path):
    return FileManager(workspace_dir=tmp_path)


def test_create_file(fm):
    fm.create_file("design.md", "# Design Doc\n")
    assert fm.read_file("design.md") == "# Design Doc\n"


def test_list_files(fm):
    fm.create_file("a.md", "a")
    fm.create_file("b.md", "b")
    files = fm.list_files()
    assert set(files) == {"a.md", "b.md"}


def test_read_nonexistent_file(fm):
    with pytest.raises(FileNotFoundError):
        fm.read_file("nope.md")


def test_acquire_lock(fm):
    fm.create_file("doc.md", "hello")
    assert fm.acquire_lock("doc.md", "agent1") is True
    lock = fm.get_lock_info("doc.md")
    assert lock["agent_id"] == "agent1"


def test_acquire_lock_conflict(fm):
    fm.create_file("doc.md", "hello")
    fm.acquire_lock("doc.md", "agent1")
    assert fm.acquire_lock("doc.md", "agent2") is False


def test_release_lock(fm):
    fm.create_file("doc.md", "hello")
    fm.acquire_lock("doc.md", "agent1")
    fm.release_lock("doc.md", "agent1")
    assert fm.get_lock_info("doc.md") is None


def test_release_lock_wrong_agent(fm):
    fm.create_file("doc.md", "hello")
    fm.acquire_lock("doc.md", "agent1")
    with pytest.raises(ValueError, match="not held by"):
        fm.release_lock("doc.md", "agent2")


def test_write_locked_file(fm):
    fm.create_file("doc.md", "old")
    fm.acquire_lock("doc.md", "agent1")
    fm.write_file("doc.md", "new", "agent1")
    assert fm.read_file("doc.md") == "new"


def test_write_without_lock(fm):
    fm.create_file("doc.md", "old")
    with pytest.raises(PermissionError, match="lock"):
        fm.write_file("doc.md", "new", "agent1")


def test_write_wrong_lock_holder(fm):
    fm.create_file("doc.md", "old")
    fm.acquire_lock("doc.md", "agent1")
    with pytest.raises(PermissionError, match="held by agent1"):
        fm.write_file("doc.md", "new", "agent2")


def test_lock_expiry(fm):
    fm.create_file("doc.md", "hello")
    fm.acquire_lock("doc.md", "agent1", timeout_seconds=0)
    # Lock should be expired immediately
    assert fm.acquire_lock("doc.md", "agent2") is True


def test_release_all_for_agent(fm):
    fm.create_file("a.md", "a")
    fm.create_file("b.md", "b")
    fm.acquire_lock("a.md", "agent1")
    fm.acquire_lock("b.md", "agent1")
    fm.release_all_locks("agent1")
    assert fm.get_lock_info("a.md") is None
    assert fm.get_lock_info("b.md") is None
