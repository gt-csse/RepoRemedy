"""Atomic receipt persistence and exclusive local access."""

import datetime
from pathlib import Path

import pytest

from RepoRemedy.publication.receipts import ReceiptStore, PublicationReceipt, PublicationError


def test_store_preserves_receipts_and_excludes_parallel_publishers(tmp_path):
    path = tmp_path / "receipts.json"
    with ReceiptStore(path, "acme/demo") as store:
        store.journal.receipts["remedy"] = PublicationReceipt(
            remedy_id="remedy",
            route="issue",
            base_commit="A" * 40,
            content_sha256="b" * 64,
            updated_at=datetime.datetime.now(datetime.UTC),
        )
        store.save()
        with pytest.raises(PublicationError, match="locked"):
            with ReceiptStore(path, "acme/demo"):
                pass
    with ReceiptStore(path, "acme/demo") as store:
        assert store.journal.receipts["remedy"].base_commit == "a" * 40
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize(
    "content",
    [
        "not-json",
        '{"repository":"other/repo"}',
        '{"repository":"acme/demo","receipts":{"other":{"remedy_id":"remedy","route":"issue","base_commit":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","content_sha256":"hash","updated_at":"2026-01-01T00:00:00Z"}}}',
    ],
)
def test_invalid_journal_is_not_overwritten_and_lock_is_released(tmp_path, content):
    path = tmp_path / "receipts.json"
    path.write_text(content)
    with pytest.raises(ValueError):
        with ReceiptStore(path, "acme/demo"):
            pass
    assert path.read_text() == content
    assert not path.with_name(path.name + ".lock").exists()


def test_failed_replace_preserves_previous_file_and_cleans_temporary(tmp_path, monkeypatch):
    path = tmp_path / "receipts.json"
    with ReceiptStore(path, "acme/demo"):
        pass
    before = path.read_bytes()

    def fail(*args):
        raise OSError("disk failure")

    monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(OSError):
        with ReceiptStore(path, "acme/demo"):
            pass
    assert path.read_bytes() == before and list(tmp_path.iterdir()) == [path]


def test_exception_releases_lock(tmp_path):
    path = tmp_path / "receipts.json"
    with pytest.raises(RuntimeError):
        with ReceiptStore(path, "acme/demo"):
            raise RuntimeError("interrupted")
    with ReceiptStore(path, "acme/demo"):
        pass
