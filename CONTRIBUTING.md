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

## Why the matcher looks like that

`match.py` is full of rules that look over-specific until you know what they
are for. Each one below is a real bug, found by running against a real library,
and each is pinned by a test. **If a test here fails, assume the change is
wrong before assuming the test is.**

- **`normalize()` is not an identity.** It strips brackets, so "Rockin' in the
  Free World", "(edit)", "(live)" and "(LP version)" all collapse to one
  string. Group and index by `identity()`, never by `normalize()`.
- **Compare the whole qualifying phrase, not the keyword.** Matching only the
  keyword made "(Part 1)" and "(Part 2)" identical — both merely "part" — which
  let one album track satisfy two separate catalogue entries.
- **Qualifiers count only where they can be appended**, i.e. in brackets or
  after a trailing dash. Scan the whole title and the song *Live Is Life* is
  reported as a live recording.
- **Strip track numbers narrowly.** The obvious regex turns "95 BPM" into "BPM"
  and "365 Tage" into "Tage", and both then read as missing.
- **Generic titles collide across artists.** Searching the whole library is what
  catches a collaboration filed under whoever was credited first — but every rap
  album has an "Intro", so a match outside the artist's own folder proves
  nothing. See `GENERIC_TITLES`.
- **Duration can veto a title match.** A radio edit and the album cut often
  share a title exactly.

One more, which costs an hour if you meet it cold: **a `\b` in a regex can
arrive as a literal backspace byte** if the file was written through a shell
heredoc. If a pattern mysteriously never matches, check it with
`grep … | cat -A` before rewriting it.

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
