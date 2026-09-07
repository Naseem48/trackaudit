# trackaudit

Find out what a music library is actually missing.

## What this is, and why it exists

Library managers (Lidarr and friends) measure completeness against their own
metadata source, which is MusicBrainz. For a great deal of music - German rap,
Turkish pop, Afrobeats, most things not sung in English - MusicBrainz is badly
incomplete. The library then reports itself complete while whole releases are
missing. Not merely missing: **invisible**, because a tool cannot show you a gap
it does not know exists.

This tool compares three sources that disagree and names *which* disagreement
each finding is:

    A  the catalogue   what the artist released           (Deezer, keyless)
    B  the disk         what is actually there            (a walk)
    C  the app          what the library manager believes (Lidarr, optional)

Naming the disagreement is the point. "The app lost the file" and "two entries
want one recording" look identical in any other tool and have completely
different remedies - and confusing them causes damage.

It came out of a long repair session on a real 3,700-file library, where the
same handful of failures kept recurring. Nearly every rule in `match.py` exists
because something concrete went wrong; the docstrings say what.

## Non-negotiables

These are settled design decisions, not open questions. Do not "improve" them
away:

1. **Nobody hosts this.** No server, no accounts, no database, no service the
   user depends on. It is a CLI that runs on the user's machine and writes an
   HTML file. If the repo vanished, every copy keeps working. Reject
   suggestions that need hosting.
2. **Never guess when guessing moves a file.** `UNCERTAIN` is a real, correct
   answer. A wrong `SAME` mis-files someone's music; declining to decide costs
   nothing. Callers must treat `UNCERTAIN` as "do not touch", never as a match.
3. **No dependencies.** Standard library only. `match.py` in particular must
   stay importable by anything (beets plugins, soularr forks) with zero install
   cost.
4. **Report first.** Writing is opt-in via `--apply`, limited to the two
   reversible actions (rescan an artist, retire a duplicate *single* entry),
   and writes an undo file before touching anything. Nothing is ever deleted,
   moved, or re-tagged.
5. **Explain why in the code.** Comments say what broke, not what the line
   does. That is what stops a hard-won rule being simplified away later.

## Layout

| file | role |
|---|---|
| `src/trackaudit/match.py` | the matcher. No I/O, no deps. The reusable core |
| `src/trackaudit/catalogue.py` | Deezer provider; implement `Catalogue` to add others |
| `src/trackaudit/library.py` | the disk walk. Reads file names, not tags |
| `src/trackaudit/arr.py` | Lidarr client. Optional |
| `src/trackaudit/audit.py` | turns the three sources into findings |
| `src/trackaudit/report.py` | self-contained HTML |
| `src/trackaudit/cli.py` | argparse entry point |
| `tests/corpus.json` | **the most valuable file here** - real title pairs and their correct verdicts |

## Traps that have already bitten this code

Each of these was a real bug, found by running against a real library. The
tests pin all of them; if a test here fails, assume the change is wrong before
assuming the test is.

- **Container paths.** Lidarr in Docker reports `/music/...` while the host has
  `/mnt/ssd/music/...`. Comparing them directly marked 46% of a real library as
  unmanaged. Hence `--path-map`.
- **`normalize()` is not an identity.** It strips brackets, so "Rockin' in the
  Free World", "(edit)", "(live)" and "(LP version)" all collapse to one
  string. Group and index by `identity()`, never by `normalize()`.
- **Qualifier keywords are not enough.** Comparing only the matched keyword made
  "(Part 1)" and "(Part 2)" identical - both merely "part" - which let one album
  track satisfy two catalogue entries. Compare the whole phrase.
- **Qualifiers are only read where they can be appended** (brackets, after a
  trailing dash). Scanning the whole title reports the song "Live Is Life" as a
  live recording.
- **Track-number stripping must be narrow.** The obvious regex turns "95 BPM"
  into "BPM" and "365 Tage" into "Tage", and both then read as missing.
- **Generic titles collide across artists.** Searching the whole library catches
  collaborations filed under the other credited artist, but every rap album has
  an "Intro". See `GENERIC_TITLES`.
- **Lidarr has no `RescanArtist` command.** It is `RefreshArtist`; the other
  returns a 500 with "Sequence contains no matching element".
- **Lidarr answers 500 to a large monitor batch.** Chunk it, and fall back to
  one at a time so a single bad id does not cost the rest their change.
- **`wanted/missing` is album-level.** Track-level truth needs the track
  endpoint, one call per album.
- **A `\b` in a regex can arrive as a literal backspace byte** if the file is
  written through a shell heredoc. Write regexes with the Write tool, and check
  with `grep | cat -A` if a pattern mysteriously never matches.

## Working on it

```bash
pip install -e ".[dev]"
pytest                                # 95 tests, no network, no Lidarr needed
python scripts/validate_corpus.py     # the corpus must stay well-formed
```

Tests use fakes for the catalogue and the app, so they never touch the network.
Keep it that way - CI runs on Linux, macOS and Windows across Python 3.9-3.13.

To try it against something real:

```bash
trackaudit --library /path/to/music --artist "Some Artist" --out /tmp/r.html
```

## Releasing

PyPI publishing uses **Trusted Publishing** (OIDC) - there is no API token in
this repo and there should never be one. Bump `version` in `pyproject.toml`
*and* `__version__` in `src/trackaudit/__init__.py`, then tag `vX.Y.Z` and push
the tag. `.github/workflows/publish.yml` refuses to publish if the tag and the
version disagree, because PyPI never allows re-uploading a version.

## Contributions

The intended contribution surface is a **test case, not code**: a user who hit a
wrong match adds the pair to `tests/corpus.json`. Issue templates in
`.github/ISSUE_TEMPLATE/` collect exactly the fields that a corpus entry needs.
Keep that barrier low - it is the mechanism by which the tool learns about
languages and conventions the author does not know.
