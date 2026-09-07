<!--
Adding a title pair to tests/corpus.json? That is the most welcome kind of PR
here, and you can delete everything below except the first line.

If your new case FAILS, open the PR anyway and say so. A documented failure is
more useful than silence.
-->

## What this changes

## Why

<!-- If it fixes a matching bug, what real pair of titles went wrong? -->

## Checklist

- [ ] `pytest` passes (or the new corpus case fails and I have said so above)
- [ ] `python scripts/validate_corpus.py` passes, if I touched the corpus
- [ ] No new dependencies in `src/trackaudit/match.py` — the matcher stays importable by anything
- [ ] Anything that writes is behind `--apply`, reversible, and writes an undo file first
