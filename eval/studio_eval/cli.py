"""`studio-eval` command line: run, compare, fixtures."""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import os
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import studio_eval

from .client import ChatResult, StudioClient, StudioError
from .golden import GoldenEntry, GoldenError, check_evidence, load_golden
from .metrics import abstention_scores, retrieval_scores
from .report import build_result, compare, summary_table, write_result

EVAL_DIR = Path(studio_eval.__file__).parent.parent
CORPUS_FOLDER = "Eval corpus"
PAGE_SEPARATOR = "\n\n<!-- page {n} -->\n\n"


class UsageError(Exception):
    pass


def settings_from_env() -> dict:
    env = os.environ.get
    samples = env("STUDIO_EVAL_SAMPLES_DIR")
    return {
        "studio_url": env("STUDIO_EVAL_URL", "http://localhost:8900"),
        "user": env("STUDIO_EVAL_USER", "admin"),
        "password": env("STUDIO_EVAL_PASSWORD", "password"),
        "judge_base_url": env("STUDIO_EVAL_JUDGE_BASE_URL", "http://localhost:11434/v1"),
        "judge_model": env("STUDIO_EVAL_JUDGE_MODEL", "qwen3"),
        "embed_model": env("STUDIO_EVAL_EMBED_MODEL", "nomic-embed-text"),
        "samples_dir": (
            Path(samples) if samples else (EVAL_DIR / "../../../sample_images").resolve()
        ),
    }


def _fmt(value: float | None) -> str:
    return "—" if value is None else f"{value:.3f}"


def _open_corpus(client, settings: dict) -> tuple[str, dict[str, str]]:
    client.login()
    folder_id = client.ensure_folder(CORPUS_FOLDER)
    return folder_id, client.ensure_corpus(folder_id, settings["samples_dir"])


async def _ask_and_grade(
    client, judge, entries: list[GoldenEntry], folder_id: str, concurrency: int
) -> tuple[list[dict], list[str]]:
    gate = asyncio.Semaphore(concurrency)
    total = len(entries)
    rerank_seen: list[str] = []

    async def grade(i: int, entry: GoldenEntry, result: ChatResult) -> dict:
        metrics = {**retrieval_scores(entry, result), **abstention_scores(entry, result)}
        if result.error:
            print(f"[{i}/{total}] {entry.id}: ERROR {result.error}")
        else:
            async with gate:
                metrics.update(await judge.score(entry, result))
            print(
                f"[{i}/{total}] {entry.id}: hit={_fmt(metrics['hit'])} "
                f"mrr={_fmt(metrics['mrr'])} graded"
            )
        return {
            "id": entry.id,
            "kind": entry.kind,
            "lang": entry.lang,
            "question": entry.question,
            "answer": result.answer,
            "citations": [dataclasses.asdict(c) for c in result.citations],
            "rerank": result.rerank,
            "error": result.error,
            "metrics": metrics,
        }

    tasks: list[asyncio.Task] = []
    try:
        for i, entry in enumerate(entries, start=1):
            # ask blocks on the Studio chat; a thread keeps earlier entries grading meanwhile
            result = await asyncio.to_thread(client.ask, entry.question, folder_id)
            if result.rerank:
                rerank_seen.append(result.rerank)
            tasks.append(asyncio.create_task(grade(i, entry, result)))
        rows = list(await asyncio.gather(*tasks))
    finally:
        for t in tasks:
            t.cancel()
    return rows, sorted(set(rerank_seen))


def cmd_run(args, client_factory, judge_factory) -> int:
    settings = settings_from_env()
    entries = load_golden(args.golden, settings["samples_dir"])
    for problem in check_evidence(entries, EVAL_DIR / "fixtures" / "extracted"):
        print(f"warning: {problem}", file=sys.stderr)
    if args.only:
        unknown = sorted(set(args.only) - {e.id for e in entries})
        if unknown:
            raise GoldenError(f"unknown ids for --only: {', '.join(unknown)}")
        entries = [e for e in entries if e.id in set(args.only)]

    with client_factory(settings["studio_url"], settings["user"], settings["password"]) as client:
        folder_id, _ = _open_corpus(client, settings)
        judge = judge_factory(
            settings["judge_base_url"], settings["judge_model"], settings["embed_model"]
        )
        rows, rerank_seen = asyncio.run(
            _ask_and_grade(client, judge, entries, folder_id, args.concurrency)
        )

    result = build_result(args.label, settings, rows, rerank_seen)
    path = write_result(result, EVAL_DIR / "results")
    print()
    print(summary_table(result))
    print(f"\nwrote {path}")
    return 0


def cmd_fixtures(client_factory) -> int:
    settings = settings_from_env()
    out_dir = EVAL_DIR / "fixtures" / "extracted"
    with client_factory(settings["studio_url"], settings["user"], settings["password"]) as client:
        _, corpus = _open_corpus(client, settings)
        out_dir.mkdir(parents=True, exist_ok=True)
        for name, doc_id in sorted(corpus.items()):
            pages = client.extracted_text(doc_id)
            text = "".join(
                (PAGE_SEPARATOR.format(n=n) if i else "") + pages[n]
                for i, n in enumerate(sorted(pages))
            )
            path = out_dir / f"{name}.md"
            path.write_text(text, encoding="utf-8")
            print(path)
    return 0


def _load_result(path: str) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise UsageError(f"cannot read {path}: {exc.strerror or exc}") from exc
    except ValueError as exc:
        raise UsageError(f"{path} is not valid JSON: {exc}") from exc


def cmd_compare(args) -> int:
    print(compare(_load_result(args.a), _load_result(args.b)))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="studio-eval", description="Evaluate Studio Ask quality.")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="ask every golden question and score the answers")
    run.add_argument("--label", default="run", help="name used in the result file (default: run)")
    run.add_argument(
        "--golden",
        type=Path,
        default=EVAL_DIR / "golden.yaml",
        help="golden set (default: eval/golden.yaml)",
    )
    run.add_argument("--only", nargs="+", metavar="ID", help="run only these golden ids")
    run.add_argument(
        "--concurrency", type=int, default=2, help="concurrent judge gradings (default: 2)"
    )

    cmp_ = sub.add_parser("compare", help="compare two result files")
    cmp_.add_argument("a", metavar="A.json")
    cmp_.add_argument("b", metavar="B.json")

    sub.add_parser("fixtures", help="save extracted text of the corpus to eval/fixtures/extracted")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    client_factory: Callable = StudioClient,
    judge_factory: Callable | None = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "run" and args.concurrency < 1:
        parser.error("--concurrency must be >= 1")
    try:
        if args.command == "run":
            if judge_factory is None:
                from .judge import Judge as judge_factory
            return cmd_run(args, client_factory, judge_factory)
        if args.command == "fixtures":
            return cmd_fixtures(client_factory)
        return cmd_compare(args)
    except (StudioError, GoldenError, UsageError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
