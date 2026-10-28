"""Result JSON, console summary, and run-to-run comparison."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .metrics import aggregate

_TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_UNSAFE_LABEL = re.compile(r"[^A-Za-z0-9._-]+")


def rerank_counts(rows: list[dict]) -> dict[str, int]:
    """Rows per rerank status; errored rows have no status and are left out."""
    counts: dict[str, int] = {}
    for r in rows:
        if not r.get("error"):
            status = r.get("rerank") or "none"
            counts[status] = counts.get(status, 0) + 1
    return dict(sorted(counts.items()))


def _counts_text(counts: dict[str, int]) -> str:
    return ", ".join(f"{k}={v}" for k, v in counts.items()) or "—"


def build_result(
    label: str,
    settings: dict,
    rows: list[dict],
    rerank_seen: list[str],
    *,
    note: str | None = None,
    partial: bool = False,
) -> dict:
    return {
        "label": label,
        "timestamp": datetime.now(timezone.utc).strftime(_TS_FORMAT),
        "note": note,
        "partial": partial,
        "studio_url": settings["studio_url"],
        "judge_model": settings["judge_model"],
        # the grader's embedding model, not Studio's
        "judge_embed_model": settings["embed_model"],
        "rerank_statuses": sorted({s for s in rerank_seen if s is not None}),
        "rerank_counts": rerank_counts(rows),
        "rows": rows,
        "aggregates": aggregate(rows),
    }


def write_result(result: dict, results_dir: Path) -> Path:
    stamp = datetime.strptime(result["timestamp"], _TS_FORMAT).strftime("%Y%m%dT%H%M%SZ")
    label = _UNSAFE_LABEL.sub("-", result["label"]).strip("-") or "run"
    results_dir = Path(results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    path = results_dir / f"{stamp}-{label}.json"
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _sections(aggregates: dict) -> list[tuple[str, dict]]:
    sections = [("overall", aggregates["overall"])]
    for group in ("by_kind", "by_lang"):
        for key, metrics in sorted(aggregates[group].items()):
            sections.append((f"{group}: {key}", metrics))
    return sections


def _num(value: float | None) -> str:
    return "—" if value is None else f"{value:.3f}"


def summary_table(result: dict) -> str:
    errors = sum(1 for r in result["rows"] if r.get("error"))
    lines = [f"label: {result['label']}  ({result['timestamp']})"]
    if result.get("note"):
        lines.append(f"note: {result['note']}")
    if result.get("partial"):
        lines.append("PARTIAL: the run stopped early; rows below are those completed")
    lines += [
        f"entries: {len(result['rows'])}  errors: {errors}",
        f"rerank: {_counts_text(rerank_counts(result['rows']))}",
    ]
    for title, metrics in _sections(result["aggregates"]):
        lines += ["", f"[{title}]"]
        for name, stat in sorted(metrics.items()):
            lines.append(
                f"  {name:<18} {_num(stat['mean']):>7}  n={stat['n']} skipped={stat['skipped']}"
            )
    return "\n".join(lines)


def _describe(side: str, result: dict) -> list[str]:
    embed = result.get("judge_embed_model", result.get("embed_model"))
    lines = [
        f"{side}: {result['label']} ({result['timestamp']})"
        + ("  PARTIAL" if result.get("partial") else "")
    ]
    if result.get("note"):
        lines.append(f"   note: {result['note']}")
    lines.append(f"   judge: {result.get('judge_model')}  judge embed: {embed}")
    errors = sum(1 for r in result["rows"] if r.get("error"))
    lines.append(f"   errors: {errors}  rerank: {_counts_text(rerank_counts(result['rows']))}")
    return lines


def _mean_n(stat: dict | None) -> str:
    if stat is None:
        return f"{'—':>7} {'(n=0)':>7}"
    return f"{_num(stat['mean']):>7} {'(n=' + str(stat['n']) + ')':>7}"


def compare(a: dict, b: dict) -> str:
    lines = _describe("A", a) + _describe("B", b)
    sec_a, sec_b = dict(_sections(a["aggregates"])), dict(_sections(b["aggregates"]))
    titles = ["overall"] + sorted((set(sec_a) | set(sec_b)) - {"overall"}, key=_section_order)
    for title in titles:
        ma, mb = sec_a.get(title, {}), sec_b.get(title, {})
        lines += ["", f"[{title}]", f"  {'metric':<18} {'A':>15} {'B':>15} {'delta':>8}"]
        for name in sorted(set(ma) | set(mb)):
            va = ma.get(name, {}).get("mean")
            vb = mb.get(name, {}).get("mean")
            delta = "—" if va is None or vb is None else f"{vb - va:+.3f}"
            lines.append(
                f"  {name:<18} {_mean_n(ma.get(name)):>15} {_mean_n(mb.get(name)):>15} {delta:>8}"
            )
    ids_a, ids_b = {r["id"] for r in a["rows"]}, {r["id"] for r in b["rows"]}
    lines += ["", f"only in A: {', '.join(sorted(ids_a - ids_b)) or '—'}"]
    lines.append(f"only in B: {', '.join(sorted(ids_b - ids_a)) or '—'}")
    return "\n".join(lines)


def _section_order(title: str) -> tuple[int, str]:
    return (0 if title.startswith("by_kind") else 1, title)
