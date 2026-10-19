"""Tests for the subagent work queue: ``e2e next-batch`` / ``e2e ingest-batch``."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from contingency_dsl_e2e_roundtrip import batch as batch_mod
from contingency_dsl_e2e_roundtrip import cli, config


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "corpus"
    root.mkdir()
    monkeypatch.chdir(tmp_path)
    config.set_corpus_root(root)
    yield root
    config.set_corpus_root(Path("corpus"))


def _write_queue(corpus: Path, dois: list[str]) -> Path:
    work = corpus / "work"
    work.mkdir(parents=True, exist_ok=True)
    queue = work / "classify-queue.jsonl"
    queue.write_text(
        "".join(
            json.dumps({"doi": d, "method_text": f"Method of {d}"}) + "\n"
            for d in dois
        ),
        encoding="utf-8",
    )
    return queue


def test_default_paths_live_under_corpus_work(corpus: Path) -> None:
    work = corpus.resolve() / "work"
    assert batch_mod.default_queue_path() == work / "classify-queue.jsonl"
    assert batch_mod.default_results_path() == work / "classify-results.jsonl"
    assert batch_mod.default_pending_dir() == work / "pending"


def test_next_batch_emits_unclassified_and_writes_prompts(corpus: Path) -> None:
    queue = _write_queue(corpus, ["10.1/a", "10.1/b", "10.1/c"])
    results = queue.with_name("classify-results.jsonl")
    results.write_text(json.dumps({"doi": "10.1/a", "procedures": []}) + "\n")
    pending = queue.with_name("pending")

    items, remaining = batch_mod.next_batch(
        1, queue_path=queue, results_path=results, pending_dir=pending
    )

    assert [i.doi for i in items] == ["10.1/b"]
    assert remaining == 2
    text = items[0].prompt_file.read_text(encoding="utf-8")
    assert text == "DOI: 10.1/b\n\nMethod section:\nMethod of 10.1/b"
    assert items[0].prompt_file == pending / "10.1_b.txt"


def test_next_batch_rejects_non_positive(corpus: Path) -> None:
    queue = _write_queue(corpus, ["10.1/a"])
    with pytest.raises(ValueError):
        batch_mod.next_batch(0, queue_path=queue)


def test_next_batch_missing_queue_raises(corpus: Path) -> None:
    with pytest.raises(FileNotFoundError):
        batch_mod.next_batch(1)


def test_ingest_batch_appends_valid_and_cleans_up(corpus: Path) -> None:
    queue = _write_queue(corpus, ["10.1/a", "10.1/b"])
    batch_mod.next_batch(2, queue_path=queue)
    pending = batch_mod.default_pending_dir()
    assert (pending / "10.1_a.txt").exists()

    batch_file = corpus / "work" / "batch-results.jsonl"
    batch_file.write_text(
        json.dumps({"doi": "10.1/a", "procedures": ["operant/atomic"]}) + "\n"
        + "not json\n"
        + json.dumps({"doi": "10.1/b", "procedures": "x"}) + "\n",
        encoding="utf-8",
    )

    appended, skipped = batch_mod.ingest_batch(batch_file)

    assert (appended, skipped) == (1, 2)
    assert not batch_file.exists()
    assert not (pending / "10.1_a.txt").exists()
    assert (pending / "10.1_b.txt").exists()
    rows = [
        json.loads(line)
        for line in batch_mod.default_results_path().read_text().splitlines()
    ]
    assert rows == [
        {
            "doi": "10.1/a",
            "procedures": ["operant/atomic"],
            "model": batch_mod.DEFAULT_SUBAGENT_MODEL_TAG,
        }
    ]

    # Already-ingested DOIs are no longer handed out.
    items, remaining = batch_mod.next_batch(5, queue_path=queue)
    assert [i.doi for i in items] == ["10.1/b"]
    assert remaining == 1


def test_ingest_batch_is_append_only(corpus: Path) -> None:
    results = batch_mod.default_results_path()
    results.parent.mkdir(parents=True)
    results.write_text('{"doi": "10.1/old", "procedures": []}\n')
    batch_file = corpus / "b.jsonl"
    batch_file.write_text('{"doi": "10.1/new", "procedures": [], "model": "m"}\n')

    batch_mod.ingest_batch(batch_file)

    lines = results.read_text().splitlines()
    assert lines[0] == '{"doi": "10.1/old", "procedures": []}'
    assert json.loads(lines[1]) == {"doi": "10.1/new", "procedures": [], "model": "m"}


def test_cli_next_batch_prints_one_line(
    corpus: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_queue(corpus, ["10.1/a", "10.1/b"])

    rc = cli.main(["--corpus", str(corpus), "next-batch", "1"])

    out = capsys.readouterr()
    assert rc == 0
    lines = out.out.strip().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["doi"] == "10.1/a"
    assert Path(row["prompt_file"]).is_file()
    assert "# emitted=1 remaining=2" in out.err


def test_cli_ingest_batch_reads_stdin(
    corpus: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "sys.stdin", io.StringIO('{"doi": "10.1/a", "procedures": ["x"]}\n')
    )

    rc = cli.main(["--corpus", str(corpus), "ingest-batch", "-"])

    assert rc == 0
    assert "appended=1 skipped=0" in capsys.readouterr().out
    assert batch_mod.default_results_path().read_text().count("\n") == 1


def test_cli_ingest_batch_missing_file(
    corpus: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = cli.main(["--corpus", str(corpus), "ingest-batch", "nope.jsonl"])
    assert rc == 2
    assert "not a file" in capsys.readouterr().err
