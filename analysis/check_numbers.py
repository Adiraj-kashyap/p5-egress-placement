"""M16 A3: every number quoted in a report text appears in a generated table.

Numbers are tokens like 481.18, 1,028.79, 0.0480, 25 (commas removed before comparing).
Identifiers are not numbers: a digit run glued to a letter or hyphen (T1, H2, F5, D-039,
x0.75, n4) is skipped, as are ISO dates. Tables = docs/report/tables/*.md.

    python -m analysis.check_numbers                       # checks docs/report/results.md
    python -m analysis.check_numbers docs/report/verdicts.md
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TABLES = ROOT / "docs" / "report" / "tables"
# A whole number token, optionally followed by a unit suffix x or % (e.g. 3.68x, 21.08%);
# (?!\.?\d|,\d) stops the regex from backtracking into a truncated prefix such as 5543 of 5543.62x.
NUM = re.compile(r"(?<![\w.\-:/`])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?!\.?\d|,\d)(?:x|%)?(?![\w\-:])")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def numbers(text: str) -> list[str]:
    text = DATE.sub(" ", text)
    text = re.sub(r"`[^`]*`", " ", text)  # code spans: file names, commands, location ids
    return [m.group(1).replace(",", "").rstrip(".") for m in NUM.finditer(text)]


def table_numbers() -> set[str]:
    out: set[str] = set()
    for p in sorted(TABLES.glob("*.md")):
        text = DATE.sub(" ", p.read_text(encoding="utf-8"))
        out.update(m.group(1).replace(",", "").rstrip(".") for m in NUM.finditer(text))
        out.update(m.replace(",", "") for m in re.findall(r"\d[\d,]*(?:\.\d+)?", text))
    return out


def check(path: Path) -> tuple[int, list[str]]:
    nums = numbers(path.read_text(encoding="utf-8"))
    known = table_numbers()
    missing = sorted({n for n in nums if n not in known}, key=lambda s: float(s))
    return len(nums), missing


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    paths = [ROOT / a for a in argv] or [ROOT / "docs" / "report" / "results.md"]
    rc = 0
    for p in paths:
        n, missing = check(p)
        rel = p.relative_to(ROOT).as_posix()
        if missing:
            rc = 1
            print(f"{rel}: {n} numbers, {len(missing)} NOT in tables: {missing}")
        else:
            print(f"{rel}: {n} numbers, all found in docs/report/tables/*.md")
    return rc


if __name__ == "__main__":
    sys.exit(main())
