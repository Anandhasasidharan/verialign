"""Rebuild the fixed FEVER slice from the official development and wiki files."""

import argparse
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from unicodedata import normalize
from urllib.parse import quote
from zipfile import ZipFile

LABELS = {"SUPPORTS": "verified", "REFUTES": "contradicted", "NOT ENOUGH INFO": "unverifiable"}
PER_LABEL = 100
SAMPLE_SEED = "verialign-fever-dev-v1"
TITLE_TOKENS = {"-LRB-": "(", "-RRB-": ")", "-LSB-": "[", "-RSB-": "]", "-COLON-": ":"}
LEADING_ID = re.compile(rb'\s*\{\s*"id"\s*:\s*("(?:[^"\\]|\\.)*")')


def wikipedia_url(page: str) -> str:
    for token, character in TITLE_TOKENS.items():
        page = page.replace(token, character)
    return f"https://en.wikipedia.org/wiki/{quote(normalize('NFC', page), safe='')}"


def normalize_claim(text: str) -> str:
    return " ".join(text.split()).casefold().rstrip(".!?")


def sample_claims(
    dev: Path, *, per_label: int = PER_LABEL, exclude: set[str] | None = None
) -> list[dict]:
    groups = defaultdict(list)
    with dev.open(encoding="utf-8") as file:
        for line in file:
            row = json.loads(line)
            groups[row["label"]].append(row)
    selected = []
    seen = None if exclude is None else set(exclude)
    for label in LABELS:
        rows = sorted(
            groups[label],
            key=lambda row: hashlib.sha256(f"{SAMPLE_SEED}:{row['id']}".encode()).digest(),
        )
        group = []
        for row in rows:
            if seen is not None:
                claim = normalize_claim(row["claim"])
                if claim in seen:
                    continue
                seen.add(claim)
            group.append(row)
            if len(group) == per_label:
                break
        if len(group) != per_label:
            raise ValueError(f"Expected at least {per_label} examples for {label}")
        selected.extend(group)
    return sorted(selected, key=lambda row: row["id"])


def read_evidence(wiki_zip: Path, selected: list[dict]) -> dict[tuple[str, int], str]:
    required = defaultdict(set)
    for row in selected:
        for group in row["evidence"]:
            for _, _, page, index in group:
                if page is not None and index is not None:
                    required[normalize("NFC", page)].add(index)
    evidence = {}
    with ZipFile(wiki_zip) as archive:
        for name in sorted(archive.namelist()):
            if not name.startswith("wiki-pages/") or not name.endswith(".jsonl"):
                continue
            with archive.open(name) as shard:
                for line in shard:
                    # Skip large text fields for pages outside the sample.
                    match = LEADING_ID.match(line)
                    if match and normalize("NFC", json.loads(match[1])) not in required:
                        continue
                    page = json.loads(line)
                    page_id = normalize("NFC", page["id"])
                    indices = required.get(page_id)
                    if not indices:
                        continue
                    for entry in page["lines"].split("\n"):
                        index, _, remainder = entry.partition("\t")
                        text = remainder.split("\t", 1)[0].strip()
                        if index.isdigit() and int(index) in indices and text:
                            evidence[page_id, int(index)] = text
    return evidence


def make_row(row: dict, evidence: dict[tuple[str, int], str]) -> dict:
    context = []
    if row["label"] != "NOT ENOUGH INFO":
        for group in row["evidence"]:
            keys = list(dict.fromkeys((page, index) for _, _, page, index in group))
            if keys and all(
                page is not None and (normalize("NFC", page), index) in evidence
                for page, index in keys
            ):
                context = [
                    {
                        "id": f"{page}:{index}",
                        "text": evidence[normalize("NFC", page), index],
                        "url": wikipedia_url(page),
                    }
                    for page, index in keys
                ]
                break
        if not context:
            raise ValueError(f"No complete evidence set for FEVER claim {row['id']}")
    return {
        "id": row["id"],
        "fever_label": row["label"],
        "expected": LABELS[row["label"]],
        "claim": row["claim"],
        "context": context,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("development_jsonl", type=Path)
    parser.add_argument("wiki_pages_zip", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--per-label", type=int, default=PER_LABEL)
    parser.add_argument(
        "--exclude-claims",
        type=Path,
        action="append",
        help="Exclude normalized claims in this existing slice. May be repeated.",
    )
    args = parser.parse_args()
    if args.per_label < 1:
        parser.error("Samples per label must be positive")
    excluded = None
    if args.exclude_claims:
        excluded = {
            normalize_claim(json.loads(line)["claim"])
            for path in args.exclude_claims
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
    selected = sample_claims(args.development_jsonl, per_label=args.per_label, exclude=excluded)
    evidence = read_evidence(args.wiki_pages_zip, selected)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rows = [make_row(row, evidence) for row in selected]
    args.output.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    print(f"Wrote {len(rows)} FEVER rows to {args.output}")


if __name__ == "__main__":
    main()
