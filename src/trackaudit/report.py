"""Render an audit as a single self-contained HTML file.

One file, no assets, no network, no fonts to fetch - so it works from a USB
stick, from a file:// URL, or published to someone's own GitHub Pages. It
respects the reader's light/dark preference and prints legibly.
"""
from __future__ import annotations

import datetime
import html
import json
from typing import List

from .audit import FINDING_TYPES, ORDER, Audit

_CSS = """
:root{color-scheme:light dark;
  --bg:#fbfbfa;--card:#fff;--fg:#1a1a18;--dim:#6b6b66;--line:#e4e4e0;
  --high:#b3261e;--med:#9a6700;--low:#4a4a46;--ok:#1a7f37;--accent:#3b5bdb}
@media (prefers-color-scheme:dark){:root{
  --bg:#131316;--card:#1b1b1f;--fg:#e8e8e6;--dim:#9a9a95;--line:#2c2c31;
  --high:#ff7b72;--med:#e3b341;--low:#9a9a95;--ok:#57ab5a;--accent:#7c93f5}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
  font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1100px;margin:0 auto;padding:32px 20px 80px}
h1{font-size:24px;margin:0 0 4px}
h2{font-size:16px;margin:32px 0 10px;font-weight:600}
.sub{color:var(--dim);font-size:13px;margin:0 0 24px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
  padding:16px;margin-bottom:14px}
.grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(210px,1fr))}
.n{font-size:26px;font-weight:650;font-variant-numeric:tabular-nums;
  line-height:1.1;margin-bottom:2px}
.n.high{color:var(--high)}.n.medium{color:var(--med)}
.n.low{color:var(--low)}.n.zero{color:var(--ok)}
.lab{font-weight:600;margin-bottom:6px}
.why{color:var(--dim);font-size:12.5px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;font-weight:600;color:var(--dim);font-size:11.5px;
  text-transform:uppercase;letter-spacing:.04em;padding:6px 10px 6px 0;
  border-bottom:1px solid var(--line)}
td{padding:6px 10px 6px 0;border-bottom:1px solid var(--line);
  vertical-align:top}
td.num{text-align:right;font-variant-numeric:tabular-nums}
tr:last-child td{border-bottom:0}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11.5px;
  color:var(--dim);word-break:break-all}
.bar{height:6px;background:var(--line);border-radius:3px;overflow:hidden;
  min-width:90px}
.bar i{display:block;height:100%}
details{margin-top:8px}
summary{cursor:pointer;color:var(--accent);font-size:13px}
.scroll{overflow-x:auto}
.pill{display:inline-block;padding:1px 7px;border-radius:99px;font-size:11px;
  border:1px solid var(--line);color:var(--dim)}
footer{margin-top:40px;color:var(--dim);font-size:12px;
  border-top:1px solid var(--line);padding-top:14px}
a{color:var(--accent)}
@media print{body{background:#fff}.card{break-inside:avoid}}
"""


def _esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _bar(percent: float) -> str:
    colour = ("var(--ok)" if percent >= 90
              else "var(--med)" if percent >= 70 else "var(--high)")
    return ('<div class="bar"><i style="width:%.0f%%;background:%s"></i></div>'
            % (max(0.0, min(100.0, percent)), colour))


def render(audit: Audit, title: str = "Library audit") -> str:
    counts = audit.counts()
    when = datetime.datetime.fromtimestamp(
        audit.generated or 0).strftime("%Y-%m-%d %H:%M")
    lib = audit.library
    total_missing = sum(a.missing for a in audit.artists)

    parts: List[str] = []
    parts.append("<!doctype html><html lang=en><head><meta charset=utf-8>")
    parts.append('<meta name=viewport content="width=device-width,'
                 'initial-scale=1">')
    parts.append("<title>%s</title><style>%s</style></head><body><div class=wrap>"
                 % (_esc(title), _CSS))

    parts.append("<h1>%s</h1>" % _esc(title))
    parts.append('<p class="sub">%d files under <span class="mono">%s</span> '
                 '&middot; %d lossless &middot; %d artist(s) &middot; '
                 'generated %s</p>'
                 % (len(lib), _esc(lib.root), lib.lossless_count,
                    len(audit.artists), _esc(when)))

    # headline
    parts.append('<div class="card"><div class="lab">'
                 'What the catalogue says you are missing</div>'
                 '<div class="n %s">%d</div>'
                 '<div class="why">Recordings this artist released that are '
                 'not in your library. Measured against a commercial '
                 'catalogue, not against your library manager&rsquo;s '
                 'metadata source &mdash; which is the point: a manager '
                 'cannot report a gap it does not know exists.</div></div>'
                 % ("ok" if not total_missing else "medium", total_missing))

    # finding tiles
    parts.append('<h2>Findings</h2><div class="grid">')
    for code in ORDER:
        label, severity, why = FINDING_TYPES[code]
        n = counts.get(code, 0)
        parts.append('<div class="card"><div class="lab">%s</div>'
                     '<div class="n %s">%d</div><div class="why">%s</div></div>'
                     % (_esc(label), "zero" if n == 0 else severity, n,
                        _esc(why)))
    parts.append("</div>")

    # per-artist completeness
    parts.append("<h2>Completeness by artist</h2>")
    parts.append('<div class="card"><div class="scroll"><table>')
    parts.append("<tr><th>artist</th><th class=num>owned</th>"
                 "<th class=num>catalogue</th><th>completeness</th>"
                 "<th class=num>missing</th><th>notes</th></tr>")
    for a in sorted(audit.artists, key=lambda x: -x.missing):
        if a.error and not a.catalogue_total:
            parts.append("<tr><td>%s</td><td colspan=5 class=why>%s</td></tr>"
                         % (_esc(a.name), _esc(a.error)))
            continue
        parts.append("<tr><td>%s</td><td class=num>%d</td><td class=num>%d</td>"
                     "<td>%s <span class=why>%.1f%%</span></td>"
                     "<td class=num>%d</td><td class=why>%s</td></tr>"
                     % (_esc(a.name), a.owned, a.catalogue_total,
                        _bar(a.percent), a.percent, a.missing,
                        _esc(a.error)))
    parts.append("</table></div></div>")

    # detail per finding type
    for code in ORDER:
        rows = [f for f in audit.findings if f.code == code]
        if not rows:
            continue
        label, _sev, why = FINDING_TYPES[code]
        applicable = sum(1 for f in rows if f.applicable)
        parts.append("<h2>%s <span class=pill>%d</span></h2>"
                     % (_esc(label), len(rows)))
        parts.append('<div class="card"><div class="why" '
                     'style="margin-bottom:10px">%s%s</div>'
                     % (_esc(why),
                        (" <b>%d can be applied automatically.</b>" % applicable)
                        if applicable else ""))
        parts.append('<div class="scroll"><table>')
        parts.append("<tr><th>artist</th><th>title</th><th>detail</th>"
                     "<th>action</th></tr>")
        for f in rows[:600]:
            release = (' <span class="why">&mdash; %s</span>' % _esc(f.release)
                       if f.release else "")
            evidence = ('<div class="mono">%s</div>' % _esc(f.evidence)
                        if f.evidence else "")
            parts.append("<tr><td>%s</td><td>%s%s</td><td class=why>%s%s</td>"
                         "<td class=why>%s</td></tr>"
                         % (_esc(f.artist), _esc(f.title), release,
                            _esc(f.detail), evidence, _esc(f.action)))
        parts.append("</table></div>")
        if len(rows) > 600:
            parts.append('<div class="why">showing 600 of %d</div>' % len(rows))
        parts.append("</div>")

    parts.append('<footer>Generated by <a href="https://github.com/'
                 'Naseem48/trackaudit">trackaudit</a>. '
                 'Nothing was modified. This file is self-contained.</footer>')
    parts.append("</div></body></html>")
    return "".join(parts)


def render_json(audit: Audit) -> str:
    return json.dumps(audit.as_dict(), indent=1, ensure_ascii=False)
