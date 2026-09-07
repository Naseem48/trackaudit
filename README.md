# trackaudit

**Find out what your music library is actually missing.**

Your library manager says you have everything. It is measuring you against its
own metadata source, and if that source has never heard of a release, it cannot
show you the gap. For a lot of music — German rap, Turkish pop, Afrobeats, most
things not sung in English — that blind spot is enormous.

trackaudit measures you against a commercial catalogue instead, and tells you
what is genuinely missing.

```
$ trackaudit --library /mnt/music --lidarr http://localhost:8686 --lidarr-key $KEY

library: 3,723 file(s), 8 artist folder(s)

  ghost                 1     on disk, the app has no record of it
  orphan                7     on disk, no entry in the app
  duplicate_entry      28     two entries competing for one recording
  invisible           229     released, and the app cannot even show it to you
  lossy_duplicate      38     lossy copy beside a lossless one

report: trackaudit-report.html
```

That `invisible: 229` is the number no other tool will give you. Those are real,
released recordings by artists you already follow, and your library manager has
never heard of a single one of them.

---

## Install

```bash
pipx install trackaudit      # or: pip install --user trackaudit
```

Python 3.9+. **No dependencies** — standard library only.

## Use it

The only required argument is your library root, the folder with one
subdirectory per artist:

```bash
trackaudit --library /mnt/music
```

That compares the catalogue against your files and writes
`trackaudit-report.html` — one self-contained page you open in a browser.
Nothing is modified, ever, unless you explicitly pass `--apply`.

Add your library manager to see the disagreements between it and your disk:

```bash
trackaudit --library /mnt/music \
           --lidarr http://localhost:8686 --lidarr-key YOUR_KEY \
           --path-map /music:/mnt/music
```

> **`--path-map` matters.** Lidarr in a container reports *container* paths.
> Without the mapping, every file you own reads as unmanaged — in testing that
> was 46% of a library flagged as a problem that did not exist.

Useful flags:

| flag | what it does |
|---|---|
| `--artist NAME` | audit one artist (repeatable) |
| `--artist-id "Samra=307151"` | pin a catalogue id, so a rename upstream cannot swap the artist |
| `--json out.json` | machine-readable findings alongside the HTML |
| `--catalogue none` | skip the network entirely; disk-and-app checks only |
| `--apply` | act on the reversible findings (see below) |
| `--undo FILE` | put back what `--apply` changed |

## What it finds

| finding | meaning | fix |
|---|---|---|
| **The app lost the file** | It is on disk; the app has no record of it | rescan |
| **Not in the library** | On disk, no entry at all — invisible to your players | import |
| **Two entries, one recording** | A single and an album track that are the same audio. One file cannot satisfy both, so one stays "missing" no matter how often you re-download it | retire one entry |
| **The app cannot see it** | Genuinely released, absent from the app's metadata source | fetch it yourself |
| **Released, not owned** | In the catalogue, not on disk | download |
| **Under another artist** | Filed under whoever was credited first | usually fine |
| **Lossy beside lossless** | An mp3 next to a flac of the same recording | delete one |
| **Too close to call** | Titles close enough that guessing would mis-file a track | confirm by hand |

That last row is deliberate. **trackaudit would rather say "I don't know" than
guess.** A wrong "these are the same" moves a file, and moved files are how
libraries get quietly destroyed.

## Applying fixes

`--apply` touches exactly two things, both reversible:

- **rescan** an artist whose file the app lost (this only makes it look again)
- **retire** a duplicate *single* entry when you already own the recording via
  an album

Before it changes anything it writes `trackaudit-undo-<timestamp>.json`, and
`--undo` restores from it. Everything else in the report is for you to decide
on. Nothing is deleted, moved, or re-tagged — not by `--apply`, not ever.

## Nobody hosts this

There is no server, no account, no database, and no service of mine that you
depend on. It is a command that runs on your machine, reads your files, and
writes an HTML file next to itself. If this repository disappeared tomorrow,
your copy would keep working.

If you want the report on a URL, publish it to **your own** GitHub Pages — see
[`examples/github-action.yml`](examples/github-action.yml).

## Use the matcher on its own

The hard part of this problem is deciding whether two titles name the same
recording. That is packaged separately and has no I/O, so you can drop it into
a beets plugin, a soularr fork, or your own scripts:

```python
from trackaudit import compare, identity, SAME, DIFFERENT, UNCERTAIN

compare("Who Wants to Live Forever",
        "Who Wants to Live Forever (Live in Budapest)")   # -> 'different'
compare("Let There Be Rock (Part 1)",
        "Let There Be Rock (Part 2)")                     # -> 'different'
compare("Weiße Orchideen", "Weisse Orchideen")            # -> 'same'
compare("ZUN9A", "Zunga")                                 # -> 'uncertain'

identity("Song (Live)") != identity("Song")               # True
```

Every rule in it exists because something went wrong:

- **Qualifiers are read only where they can be appended.** Scanning the whole
  title reports the song *Live Is Life* as a live recording.
- **The whole qualifying phrase is compared, not the keyword.** Comparing
  keywords made `(Part 1)` and `(Part 2)` identical — both merely "part" — and
  let one album track satisfy two catalogue entries.
- **Track numbers are stripped narrowly.** The obvious pattern turns `95 BPM`
  into `BPM` and `365 Tage` into `Tage`, and both then look missing.
- **Duration can veto a title match.** A radio edit and the album cut often
  share a title exactly.
- **`identity()` includes the qualifier.** Grouping by normalised title alone
  collapses *Rockin' in the Free World*, `(edit)`, `(live)` and `(LP version)`
  into one entry.

## Contributing

The most valuable thing you can add is a **test case**, not code. If trackaudit
judged two of your titles wrongly, add the pair to
[`tests/corpus.json`](tests/corpus.json) — it is three lines, and it improves
matching for everyone. See [CONTRIBUTING.md](CONTRIBUTING.md).

```bash
git clone https://github.com/Naseem48/trackaudit && cd trackaudit
pip install -e ".[dev]"
pytest
```

## Licence

MIT.
