import re
from dataclasses import dataclass
from pathlib import Path

import yaml

KINDS = {"fact", "cross_doc", "unanswerable"}
LANGS = {"en", "de", "fr", "es", "nl"}
ID_RE = re.compile(r"^[a-z0-9-]+$")


class GoldenError(Exception):
    pass


@dataclass
class Source:
    file: str
    page: int


@dataclass
class GoldenEntry:
    id: str
    question: str
    answer: str
    evidence: str | None
    sources: list[Source]
    lang: str
    kind: str


def _parse(raw: object, index: int, samples_dir: Path) -> GoldenEntry:
    if not isinstance(raw, dict):
        raise GoldenError(f"entry #{index}: must be a mapping")
    eid = raw.get("id")
    name = eid if isinstance(eid, str) and eid else f"#{index}"

    def fail(msg: str) -> GoldenError:
        return GoldenError(f"entry {name}: {msg}")

    if name.startswith("#") or not ID_RE.match(name):
        raise fail("id must be present and match [a-z0-9-]+")
    for key in ("question", "answer"):
        if not isinstance(raw.get(key), str) or not raw[key].strip():
            raise fail(f"{key} must be a non-empty string")
    kind, lang = raw.get("kind"), raw.get("lang")
    if kind not in KINDS:
        raise fail(f"kind {kind!r} not in {sorted(KINDS)}")
    if lang not in LANGS:
        raise fail(f"lang {lang!r} not in {sorted(LANGS)}")

    evidence = raw.get("evidence")
    if evidence is not None and not isinstance(evidence, str):
        raise fail("evidence must be a string")
    if kind == "fact" and not evidence:
        raise fail("evidence is required for kind fact")

    raw_sources = raw.get("sources") or []
    if not isinstance(raw_sources, list):
        raise fail("sources must be a list")
    sources: list[Source] = []
    for s in raw_sources:
        if not isinstance(s, dict) or not isinstance(s.get("file"), str):
            raise fail("each source needs a file")
        page = s.get("page")
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            raise fail(f"page for {s['file']} must be an integer >= 1")
        if not (samples_dir / s["file"]).is_file():
            raise fail(f"source file {s['file']} not found in {samples_dir}")
        sources.append(Source(s["file"], page))
    if kind == "unanswerable" and sources:
        raise fail("sources must be empty for kind unanswerable")
    if kind != "unanswerable" and not sources:
        raise fail("sources must have at least one entry")

    return GoldenEntry(name, raw["question"], raw["answer"], evidence, sources, lang, kind)


def load_golden(path: Path, samples_dir: Path) -> list[GoldenEntry]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise GoldenError("golden file must be a YAML list of entries")
    entries: list[GoldenEntry] = []
    seen: set[str] = set()
    for i, raw in enumerate(data):
        e = _parse(raw, i, samples_dir)
        if e.id in seen:
            raise GoldenError(f"entry {e.id}: duplicate id")
        seen.add(e.id)
        entries.append(e)
    return entries


def check_evidence(entries: list[GoldenEntry], fixtures_dir: Path) -> list[str]:
    problems: list[str] = []
    for e in entries:
        if e.kind != "fact":
            continue
        fixture = fixtures_dir / f"{e.sources[0].file}.md"
        if not fixture.is_file():
            problems.append(f"{e.id}: fixture {fixture.name} not found in {fixtures_dir}")
        elif e.evidence not in fixture.read_text(encoding="utf-8"):
            problems.append(f"{e.id}: evidence {e.evidence!r} not found in {fixture.name}")
    return problems
