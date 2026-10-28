"""Result JSON, console summary, and run-to-run comparison."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .metrics import aggregate

_TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_UNSAFE_LABEL = re.compile(r"[^A-Za-z0-9._-]+")


def build_result(label: str, settings: dict, rows: list[dict], rerank_seen: list[str]) -> dict:
    return {
        "label": label,
        "timestamp": datetime.now(timezone.utc).strftime(_TS_FORMAT),
        "studio_url": settings["studio_url"],
        "judge_model": settings["judge_model"],
        "embed_model": settings["embed_model"],
        "rerank_statuses": sorted({s for s in rerank_seen if s is not None}),
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
    lines = [
        f"label: {result['label']}  ({result['timestamp']})",
        f"entries: {len(result['rows'])}  errors: {errors}",
    ]
    for title, metrics in _sections(result["aggregates"]):
        lines += ["", f"[{title}]"]
        for name, stat in sorted(metrics.items()):
            lines.append(
                f"  {name:<18} {_num(stat['mean']):>7}  n={stat['n']} skipped={stat['skipped']}"
            )
    return "\n".join(lines)


def compare(a: dict, b: dict) -> str:
    lines = [f"A: {a['label']} ({a['timestamp']})", f"B: {b['label']} ({b['timestamp']})"]
    sec_a, sec_b = dict(_sections(a["aggregates"])), dict(_sections(b["aggregates"]))
    titles = ["overall"] + sorted((set(sec_a) | set(sec_b)) - {"overall"}, key=_section_order)
    for title in titles:
        ma, mb = sec_a.get(title, {}), sec_b.get(title, {})
        lines += ["", f"[{title}]", f"  {'metric':<18} {'A':>7} {'B':>7} {'delta':>8}"]
        for name in sorted(set(ma) | set(mb)):
            va = ma.get(name, {}).get("mean")
            vb = mb.get(name, {}).get("mean")
            delta = "—" if va is None or vb is None else f"{vb - va:+.3f}"
            lines.append(f"  {name:<18} {_num(va):>7} {_num(vb):>7} {delta:>8}")
    ids_a, ids_b = {r["id"] for r in a["rows"]}, {r["id"] for r in b["rows"]}
    lines += ["", f"only in A: {', '.join(sorted(ids_a - ids_b)) or '—'}"]
    lines.append(f"only in B: {', '.join(sorted(ids_b - ids_a)) or '—'}")
    return "\n".join(lines)


def _section_order(title: str) -> tuple[int, str]:
    return (0 if title.startswith("by_kind") else 1, title)
