#!/usr/bin/env python3
"""Check that tests/corpus.json is well formed.

The corpus is the contribution surface, so a malformed entry has to fail loudly
with a message that says what to fix. A pytest parametrisation would just skip
it, and the contributor would never know.

Run it directly:  python scripts/validate_corpus.py
"""
from __future__ import annotations

import collections
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CORPUS = ROOT / "tests" / "corpus.json"
VERDICTS = {"same", "different", "uncertain"}


def main() -> int:
    problems = []
    try:
        data = json.loads(CORPUS.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print("corpus.json is not valid JSON: %s" % exc)
        print("  (a trailing comma after the last entry is the usual cause)")
        return 1

    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        print("corpus.json needs a non-empty 'cases' list")
        return 1

    seen = collections.Counter()
    for index, case in enumerate(cases):
        where = "cases[%d]" % index
        if not isinstance(case, dict):
            problems.append("%s is not an object" % where)
            continue
        for field in ("a", "b", "verdict", "why"):
            if not case.get(field):
                problems.append("%s is missing %r" % (where, field))
        verdict = case.get("verdict")
        if verdict and verdict not in VERDICTS:
            problems.append("%s has verdict %r, expected one of %s"
                            % (where, verdict, ", ".join(sorted(VERDICTS))))
        if case.get("a") and case.get("b"):
            seen[tuple(sorted([case["a"], case["b"]]))] += 1

    for pair, count in seen.items():
        if count > 1:
            problems.append("duplicate case: %r vs %r appears %d times"
                            % (pair[0], pair[1], count))

    for index, case in enumerate(data.get("filenames", [])):
        where = "filenames[%d]" % index
        if not isinstance(case, dict) or not case.get("file") \
                or "title" not in case:
            problems.append("%s needs 'file' and 'title'" % where)

    if problems:
        print("corpus.json has %d problem(s):" % len(problems))
        for problem in problems:
            print("  - %s" % problem)
        return 1

    print("corpus.json ok: %d case(s), %d filename case(s)"
          % (len(cases), len(data.get("filenames", []))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
