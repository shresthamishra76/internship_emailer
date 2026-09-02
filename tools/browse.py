"""Browse matching internships on demand, instead of waiting for a digest.

    python -m tools.browse              # everything currently open that matches
    python -m tools.browse --seen       # what has already been emailed (offline)
    python -m tools.browse --days 3     # only postings first seen in last 3 days
    python -m tools.browse --html out.html

`--seen` reads data/seen_jobs.json and makes no network calls. The default
re-scrapes all 38 sources (~40s) and shows live matches, including ones already
emailed — the digest only ever shows what is new, so this is the way to see the
full set.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import sys
from collections import defaultdict

from src import config
from src.filters import apply_filters
from src.main import collect_jobs
from src.models import Job

LABELS = {"swe": "Software Engineering", "ai": "AI / Machine Learning",
          "quant": "Quant / Trading", "other": "Other"}


def from_state(days: int | None) -> list[Job]:
    state = json.load(open(config.state_path()))
    cutoff = None
    if days:
        cutoff = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    jobs = []
    for rec in state.values():
        if cutoff and (rec.get("first_seen") or "") < cutoff:
            continue
        jobs.append(Job(company=rec.get("company", "?"), title=rec.get("title", "?"),
                        url=rec.get("url", ""), locations=[]))
    return jobs


def group(jobs: list[Job]) -> dict[str, list[Job]]:
    out = defaultdict(list)
    for j in jobs:
        out[j.category or "other"].append(j)
    return out


def render_text(grouped: dict[str, list[Job]], total: int) -> str:
    lines = [f"\n{total} matching internship(s)\n" + "=" * 70]
    for cat in ("swe", "ai", "quant", "other"):
        rows = grouped.get(cat)
        if not rows:
            continue
        lines.append(f"\n{LABELS.get(cat, cat)} ({len(rows)})")
        for j in sorted(rows, key=lambda x: (x.company.lower(), x.title.lower())):
            loc = j.location_str or ""
            lines.append(f"  • {j.title} — {j.company}" + (f"  [{loc}]" if loc else ""))
            lines.append(f"      {j.url}")
    return "\n".join(lines)


def render_html(grouped: dict[str, list[Job]], total: int) -> str:
    e = html.escape
    parts = ["<meta charset='utf-8'><title>Internship matches</title>",
             "<style>body{font:14px/1.5 system-ui,sans-serif;max-width:60rem;margin:2rem auto;padding:0 1rem}"
             "h2{margin-top:2rem;border-bottom:1px solid #ddd;padding-bottom:.3rem}"
             "li{margin:.4rem 0}.c{color:#666}</style>",
             f"<h1>{total} matching internship(s)</h1>"]
    for cat in ("swe", "ai", "quant", "other"):
        rows = grouped.get(cat)
        if not rows:
            continue
        parts.append(f"<h2>{e(LABELS.get(cat, cat))} ({len(rows)})</h2><ul>")
        for j in sorted(rows, key=lambda x: (x.company.lower(), x.title.lower())):
            loc = f" <span class='c'>[{e(j.location_str)}]</span>" if j.location_str else ""
            parts.append(f"<li><a href='{e(j.url)}'>{e(j.title)}</a> "
                         f"<span class='c'>— {e(j.company)}</span>{loc}</li>")
        parts.append("</ul>")
    return "\n".join(parts)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Browse matching internships on demand")
    p.add_argument("--seen", action="store_true",
                   help="read data/seen_jobs.json instead of scraping (offline, instant)")
    p.add_argument("--days", type=int, help="with --seen, only postings first seen in the last N days")
    p.add_argument("--html", metavar="PATH", help="write an HTML page instead of printing")
    args = p.parse_args(argv)

    if args.seen:
        jobs = apply_filters(from_state(args.days))
    else:
        if args.days:
            p.error("--days only applies with --seen (live scrapes carry no first-seen date)")
        jobs = apply_filters(collect_jobs())

    grouped = group(jobs)
    if args.html:
        with open(args.html, "w") as fh:
            fh.write(render_html(grouped, len(jobs)))
        print(f"wrote {args.html} ({len(jobs)} jobs)")
    else:
        print(render_text(grouped, len(jobs)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
