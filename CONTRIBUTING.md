# Contributing

## The most useful thing you can do: add a test case

trackaudit's whole job is deciding whether two titles name the same recording.
It gets that wrong sometimes, and the cases it gets wrong are the ones nobody
anticipated — a stylised spelling, a language convention, a label's naming
habit.

**If it judged two of your titles wrongly, add the pair.** You do not need to
fix the code. A failing case is a complete, valuable contribution: it documents
the problem precisely and it stops anyone from regressing it later.

Open [`tests/corpus.json`](tests/corpus.json) and append to `cases`:

```json
{
  "a": "Hafenmelodie",
  "b": "Hafenmelodie (Slowed + Reverb)",
  "verdict": "different",
  "why": "a slowed edit is a separate recording"
}
```

`verdict` is one of:

| verdict | meaning |
|---|---|
| `same` | one file legitimately satisfies both entries |
| `different` | distinct recordings, or distinct songs |
| `uncertain` | a human should decide; the matcher must not guess |

`uncertain` is a real answer and often the correct one. Titles a letter apart,
or stylised (`ZUN9A` / `Zunga`), genuinely cannot be resolved from strings
alone. Marking those `uncertain` is better than forcing a guess.

Then run:

```bash
pip install -e ".[dev]"
pytest
python scripts/validate_corpus.py
```

If your case fails, that is fine — **open the pull request anyway** and say so.
A documented failure is more useful than silence, and someone will fix it.

## Adding a catalogue provider

Deezer is the default because it needs no key, no account and no signup, which
means anyone can run trackaudit without registering for anything. Keep that
property if you can.

Implement `Catalogue` in `src/trackaudit/catalogue.py`:

```python
class MyProvider(Catalogue):
    name = "myprovider"

    def find_artist(self, name: str) -> Artist | None: ...
    def recordings(self, artist: Artist) -> list[Recording]: ...
```

Register it in `PROVIDERS`. Deduplicate recordings by `identity()` — the same
track appears on the album, the deluxe edition and three compilations, and
counting it repeatedly overstates what is missing.

## Adding a library manager

`src/trackaudit/arr.py` reads Lidarr. Others are welcome. Two rules:

- **Read-only by default.** Writes belong behind `--apply`, must be reversible,
  and must write an undo file first.
- **Handle container paths.** Anything running in Docker reports paths from
  inside the container. Without translation, an entire library reads as
  unmanaged.

## Principles

1. **Never guess when guessing moves a file.** `uncertain` costs nothing; a
   wrong `same` costs someone their library.
2. **No dependencies in the core.** `match.py` is importable by anything, and
   it stays that way.
3. **Report first.** The tool's job is to tell you the truth. Acting on it is
   opt-in, narrow, and reversible.
4. **Explain why in the code.** Nearly every rule here exists because something
   broke. Say what broke — it stops the rule being "simplified" away later.

## Code style

Standard library only, PEP 8, four spaces. Docstrings explain *why*, not what.
CI runs on Linux, macOS and Windows across Python 3.9–3.13.
