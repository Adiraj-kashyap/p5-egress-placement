"""Acceptance checks for the paper (M21 A1, A3, A4, A5; A2 needs the PDF).

- A1  the LaTeX log has no undefined reference or citation (skipped if there is no log yet);
- A2  6 <= pages <= 8 (skipped if there is no PDF yet);
- A3  the required sections exist in main.tex;
- A4  every \\cite key is a verified literature row (I3) and every figure caption states n and a CI;
- A5  no hand-typed numbers: after removing comments, \\N{...} macros, command arguments that are
      names (labels, refs, cites, files, environments), years and section-style identifiers
      (T1, H2, B1-alt, 1-opt), no digit may remain in the prose or the math.

    python -m analysis.check_paper
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from analysis import make_bib

ROOT = Path(__file__).resolve().parents[1]
PAPER = ROOT / "paper"
TEX = PAPER / "main.tex"

SECTIONS = {"Abstract": r"\\begin\{abstract\}", "Related Work": r"\\section\{Related Work\}",
            "Method (formulation)": r"\\section\{Problem Formulation\}",
            "Method (heuristics)": r"\\section\{Heuristics",
            "Evaluation": r"\\section\{Evaluation\}",
            "Threats to Validity": r"\\section\{Threats to Validity\}",
            "References": r"\\bibliography\{"}

# arguments that are names, not prose: their digits are not numbers
NAME_ARGS = re.compile(r"\\(label|ref|eqref|cite|input|includegraphics|bibliography|bibliographystyle|"
                       r"graphicspath|documentclass|usepackage|begin|end|N|pct|usdm|setlength|"
                       r"newcommand|texttt)(\[[^\]]*\])?\{(\{[^}]*\}|[^}])*\}")
IDENT = re.compile(r"\b(?:[A-Za-z]+-?\d+(?:-\d+)?(?:-[a-z]+)?|1-opt|\d{2}[A-Z]{3}\d{4})\b")  # last: reg. no. (D-094)
YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
ALLOWED_MATH = re.compile(r"(?<![\d.])[012](?![\d.])")  # structural constants such as x in {0,1}, y >= 0
COL_SPEC = re.compile(r"p\{0\.\d+\\columnwidth\}|width=0\.\d+\\textwidth")


def strip(text: str) -> str:
    text = text.split(r"\begin{document}", 1)[-1]  # the preamble holds macro definitions only
    text = re.sub(r"(?<!\\)%.*", "", text)
    text = COL_SPEC.sub("", text)
    text = re.sub(r"\\setlength\{[^}]*\}\{[^}]*\}", "", text)
    text = re.sub(r"\\(begin|end)\{(equation|align)\}", r"$$MATH\2$$", text)
    for _ in range(3):  # nested name arguments
        text = NAME_ARGS.sub(" ", text)
    return text


def stray_digits(text: str) -> list[str]:
    body = strip(text)
    out = []
    math = re.compile(r"\$\$MATH(equation|align)\$\$.*?\$\$MATH\1\$\$|\$[^$]*\$", re.S)
    for m in math.finditer(body):
        rest = ALLOWED_MATH.sub("", IDENT.sub("", m.group(0)))
        out += [f"math: {m.group(0)[:60]!r}" for _ in [0] if re.search(r"\d", rest)]
    prose = math.sub(" ", body)
    prose = IDENT.sub("", YEAR.sub("", prose))
    for line in prose.splitlines():
        if re.search(r"\d", line):
            out.append(f"prose: {line.strip()[:80]!r}")
    return out


def main() -> int:
    tex = TEX.read_text(encoding="utf-8")
    failed = 0

    log = PAPER / "main.log"
    if log.exists():
        bad = [l for l in log.read_text(encoding="utf-8", errors="replace").splitlines()
               if re.search(r"undefined|Citation .* undefined|Reference .* undefined|There were undefined", l)]
        print(f"A1 undefined refs/citations in main.log: {len(bad)}")
        failed += bool(bad)
    else:
        print("A1 SKIP: paper/main.log not found (not compiled yet)")

    pdf = PAPER / "main.pdf"
    if pdf.exists():
        try:
            import pypdf
            pages = len(pypdf.PdfReader(str(pdf)).pages)
            print(f"A2 pages = {pages} (need 6..8)")
            failed += not 6 <= pages <= 8
        except ImportError:
            print("A2 SKIP: pypdf not installed")
    else:
        print("A2 SKIP: paper/main.pdf not found")

    missing = [k for k, pat in SECTIONS.items() if not re.search(pat, tex)]
    print(f"A3 sections present {len(SECTIONS) - len(missing)}/{len(SECTIONS)}"
          + (f"; missing {missing}" if missing else ""))
    failed += bool(missing)

    cited = {k.strip() for g in re.findall(r"\\cite\{([^}]*)\}", tex) for k in g.split(",")}
    unverified = sorted(cited - make_bib.keys())
    print(f"A4 cited keys {len(cited)}, not a verified row: {unverified or 'none'}")
    failed += bool(unverified)
    caps = re.findall(r"\\begin\{figure\*?\}.*?\\caption\{(.*?)\}\s*\\label", tex, re.S)
    weak = [c[:50] for c in caps if not (re.search(r"\$n=", c) and "CI" in c)]
    print(f"A4 figure captions {len(caps)}, missing n or CI: {weak or 'none'}")
    failed += bool(weak)

    stray = stray_digits(tex)
    print(f"A5 hand-typed numbers: {len(stray)}")
    for s in stray:
        print("   ", s)
    failed += bool(stray)

    print("RESULT:", "PASS" if not failed else f"FAIL ({failed} check(s))")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
