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
from .metrics import abstention_scores, evidence_scores, retrieval_scores
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


def _ask_all(client, entries: list[GoldenEntry], folder_id: str, rows: list[dict]) -> list:
    """Ask every question in turn; non-fatal chat errors become that row's error."""
    asked = []
    total = len(entries)
    for i, entry in enumerate(entries, start=1):
        try:
            result = client.ask(entry.question, folder_id)
        except StudioError as exc:
            if exc.fatal:
                raise
            result = ChatResult(answer="", error=str(exc))
        row = {
            "id": entry.id,
            "kind": entry.kind,
            "lang": entry.lang,
            "question": entry.question,
            "answer": result.answer,
            "citations": [dataclasses.asdict(c) for c in result.citations],
            "rerank": result.rerank,
            "error": result.error,
            "metrics": {
                **retrieval_scores(entry, result),
                **evidence_scores(entry, result),
                **abstention_scores(entry, result),
            },
        }
        rows.append(row)
        asked.append((entry, result, row))
        outcome = f"ERROR {result.error}" if result.error else "ok"
        print(f"[ask {i}/{total}] {entry.id}: {outcome}")
    return asked


async def _grade_all(judge, asked: list, concurrency: int) -> None:
    gate = asyncio.Semaphore(concurrency)
    todo = [item for item in asked if not item[1].error]
    done = 0

    async def grade(entry: GoldenEntry, result: ChatResult, row: dict) -> None:
        nonlocal done
        async with gate:
            row["metrics"].update(await judge.score(entry, result))
        done += 1
        m = row["metrics"]
        print(
            f"[grade {done}/{len(todo)}] {entry.id}: "
            f"hit={_fmt(m['hit'])} mrr={_fmt(m['mrr'])} graded"
        )

    await asyncio.gather(*(grade(*item) for item in todo))


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

    rows: list[dict] = []
    stop: tuple[int, str] | None = None
    with client_factory(settings["studio_url"], settings["user"], settings["password"]) as client:
        folder_id, _ = _open_corpus(client, settings)
        judge = judge_factory(
            settings["judge_base_url"], settings["judge_model"], settings["embed_model"]
        )
        try:
            asked = _ask_all(client, entries, folder_id, rows)
            # grading after asking keeps the judge from competing with Ask for the host
            asyncio.run(_grade_all(judge, asked, args.concurrency))
        except StudioError as exc:
            stop = (2, f"error: {exc}")
        except KeyboardInterrupt:
            stop = (130, "interrupted")

    if stop and not rows:
        print(stop[1], file=sys.stderr)
        return stop[0]
    rerank_seen = [r["rerank"] for r in rows if r["rerank"]]
    result = build_result(
        args.label, settings, rows, rerank_seen, note=args.note, partial=stop is not None
    )
    path = write_result(result, EVAL_DIR / "results")
    print()
    print(summary_table(result))
    print(f"\nwrote {path}")
    if stop:
        print(stop[1], file=sys.stderr)
        print(f"wrote partial results ({len(rows)}/{len(entries)} asked) to {path}", file=sys.stderr)
    return stop[0] if stop else 0


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
    run.add_argument(
        "--note", help='free text stored in the result, e.g. "studio embed=nomic-embed-text chat=llama3.2:3b"'
    )
    run.add_argument("--only", nargs="+", metavar="ID", help="run only these golden ids")
    run.add_argument(
        "--concurrency",
        type=int,
        default=2,
        help="concurrent judge gradings, run after all questions are asked (default: 2)",
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
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
