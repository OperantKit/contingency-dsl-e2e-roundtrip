"""CLI entrypoint: `e2e <subcommand>`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from . import agent_gen
from . import artifacts as artifacts_mod
from . import batch as batch_mod
from . import classify as classify_mod
from . import config
from . import extract as extract_mod
from . import report as report_mod
from . import roundtrip as roundtrip_mod
from . import state as state_mod
from .papers import all_dois_with_any_asset
from .procedures import discover_procedures


def _cmd_list_procedures(_: argparse.Namespace) -> int:
    for proc in discover_procedures():
        print(f"{proc.key}\t{proc.source.name}")
    return 0


def _cmd_classify(args: argparse.Namespace) -> int:
    state = state_mod.load()
    dois = [args.doi] if args.doi else all_dois_with_any_asset()
    procedures = discover_procedures()

    for doi in dois:
        extracted = extract_mod.ensure_extracted(doi)
        if extracted is None:
            print(f"[skip] {doi}: no extractable Method section", file=sys.stderr)
            continue
        _, text = extracted
        try:
            result = classify_mod.classify(doi, text, procedures=procedures)
        except classify_mod.ClassifierUnavailable as exc:
            print(f"[error] classifier unavailable: {exc}", file=sys.stderr)
            return 2
        except Exception as exc:  # pragma: no cover - network / remote errors
            print(f"[error] {doi}: {exc}", file=sys.stderr)
            continue
        state_mod.upsert_classification(
            state,
            doi,
            list(result.procedures),
            result.model,
            out_of_scope_reason=result.out_of_scope_reason,
        )
        if result.out_of_scope_reason:
            print(f"[oos] {doi}: {result.out_of_scope_reason}")
        else:
            print(f"[ok] {doi}: {', '.join(result.procedures) or '(none)'}")

    state_mod.save(state)
    return 0


def _cmd_extract(args: argparse.Namespace) -> int:
    if args.all:
        state = state_mod.load()
        dois = list(state.get("entries", {}).keys()) or all_dois_with_any_asset()
        ok = fail = 0
        for doi in dois:
            out = extract_mod.ensure_extracted(doi, force=args.force)
            if out is None:
                fail += 1
                continue
            ok += 1
        print(f"extracted ok={ok} fail={fail} total={ok + fail}")
        return 0 if fail == 0 else 0  # fails are per-paper, not fatal

    if not args.doi:
        print("[error] --doi is required unless --all is given", file=sys.stderr)
        return 2
    out = extract_mod.ensure_extracted(args.doi, force=args.force)
    if out is None:
        print(f"[fail] {args.doi}: no extractable Method section", file=sys.stderr)
        return 1
    path, _ = out
    print(str(path))
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    state = state_mod.load()
    if args.doi:
        dois = [args.doi]
    else:
        dois = [doi for doi in state.get("entries", {}).keys()
                if state["entries"][doi].get("procedures")]
    for doi in dois:
        extracted = extract_mod.ensure_extracted(doi)
        if extracted is None:
            print(f"[skip] {doi}: no extractable Method section", file=sys.stderr)
            continue
        _, text = extracted
        result = roundtrip_mod.run(doi, text)
        artifacts_mod.save(result)
        state_mod.upsert_roundtrip(state, doi, result.to_dict())
        status = "PASS" if result.ok else "FAIL"
        print(f"[{status}] {doi}: a={result.a_ast_equiv} b={result.b_reparseable} "
              f"c={result.c_text_similarity} d={result.d_notation_equiv}"
              + (f" err={result.error}" if result.error else ""))
    state_mod.save(state)
    return 0


def _cmd_report(_: argparse.Namespace) -> int:
    state = state_mod.load()
    written = report_mod.render(state)
    print(f"wrote {len(written)} files")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="e2e")
    parser.add_argument(
        "--corpus", default="corpus", metavar="DIR",
        help="Corpus directory holding state.json, doi-lists/, extracted/, generated/ "
             "(default: ./corpus)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list-procedures").set_defaults(func=_cmd_list_procedures)

    p_cls = sub.add_parser("classify")
    p_cls.add_argument("--doi")
    p_cls.add_argument("--all", action="store_true")
    p_cls.set_defaults(func=_cmd_classify)

    p_ext = sub.add_parser("extract")
    p_ext.add_argument("--doi")
    p_ext.add_argument("--all", action="store_true",
                       help="Extract every DOI known to state.json (or asset-backed DOIs)")
    p_ext.add_argument("--force", action="store_true")
    p_ext.set_defaults(func=_cmd_extract)

    p_run = sub.add_parser("run")
    p_run.add_argument("--doi")
    p_run.add_argument("--all", action="store_true")
    p_run.set_defaults(func=_cmd_run)

    sub.add_parser("report").set_defaults(func=_cmd_report)

    p_prep = sub.add_parser(
        "classify-prepare",
        help="Write a JSONL classification queue for a Claude Code subagent to consume",
    )
    p_prep.add_argument(
        "--out", default=None,
        help="Queue path (default: <corpus>/work/classify-queue.jsonl)",
    )
    p_prep.add_argument(
        "--redo", action="store_true",
        help="Enqueue every DOI regardless of existing classification",
    )
    p_prep.set_defaults(func=_cmd_classify_prepare)

    p_ing = sub.add_parser(
        "classify-ingest",
        help="Fold a subagent's classification result JSONL into state.json",
    )
    p_ing.add_argument(
        "path", nargs="?", default=None,
        help="Results JSONL (default: <corpus>/work/classify-results.jsonl)",
    )
    p_ing.set_defaults(func=_cmd_classify_ingest)

    p_next = sub.add_parser(
        "next-batch",
        help="Write prompt files for the next N unclassified queue rows and "
             "print one {doi, prompt_file} JSON line per row",
    )
    p_next.add_argument("n", type=int)
    p_next.add_argument("--queue", default=None,
                        help="Queue path (default: <corpus>/work/classify-queue.jsonl)")
    p_next.add_argument("--results", default=None,
                        help="Results path (default: <corpus>/work/classify-results.jsonl)")
    p_next.set_defaults(func=_cmd_next_batch)

    p_ib = sub.add_parser(
        "ingest-batch",
        help="Append a JSONL file of {doi, procedures} lines ('-' = stdin) to the "
             "results JSONL, then delete it and the matching prompt files",
    )
    p_ib.add_argument("path")
    p_ib.add_argument("--results", default=None,
                      help="Results path (default: <corpus>/work/classify-results.jsonl)")
    p_ib.set_defaults(func=_cmd_ingest_batch)

    sub.add_parser(
        "regenerate-agent",
        help="(Re)generate .claude/agents/procedure-classifier.md from the current taxonomy",
    ).set_defaults(func=_cmd_regenerate_agent)

    return parser


def _optional_path(value: str | None) -> Path | None:
    return Path(value) if value else None


def _cmd_classify_prepare(args: argparse.Namespace) -> int:
    path, enqueued, skipped = batch_mod.prepare_queue(
        _optional_path(args.out), skip_classified=not args.redo
    )
    print(f"wrote {path}: enqueued={enqueued} skipped={skipped}")
    return 0


def _cmd_classify_ingest(args: argparse.Namespace) -> int:
    applied, dropped = batch_mod.ingest_results(_optional_path(args.path))
    print(f"applied={applied} dropped={dropped}")
    return 0


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(path)


def _cmd_next_batch(args: argparse.Namespace) -> int:
    if args.n <= 0:
        print("[error] N must be positive", file=sys.stderr)
        return 2
    try:
        items, remaining = batch_mod.next_batch(
            args.n,
            queue_path=_optional_path(args.queue),
            results_path=_optional_path(args.results),
        )
    except FileNotFoundError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2
    for item in items:
        print(json.dumps(
            {"doi": item.doi, "prompt_file": _display_path(item.prompt_file)},
            ensure_ascii=False,
        ))
    print(f"# emitted={len(items)} remaining={remaining}", file=sys.stderr)
    return 0


def _cmd_ingest_batch(args: argparse.Namespace) -> int:
    batch_path = None if args.path == "-" else Path(args.path)
    if batch_path is not None and not batch_path.is_file():
        print(f"[error] not a file: {batch_path}", file=sys.stderr)
        return 2
    appended, skipped = batch_mod.ingest_batch(
        batch_path, results_path=_optional_path(args.results)
    )
    print(f"appended={appended} skipped={skipped}")
    return 0


def _cmd_regenerate_agent(_: argparse.Namespace) -> int:
    path = agent_gen.write_agent_markdown()
    print(f"wrote {path}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    config.set_corpus_root(Path(args.corpus))
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
