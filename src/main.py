"""Orchestrator: collect -> filter -> dedup -> notify -> save state.

Usage:
    python -m src.main                 # full run (fetch, notify, persist state)
    python -m src.main --dry-run       # fetch + filter, print what WOULD send; no send, no save
    python -m src.main --test-notify   # send one sample email + SMS to verify credentials
    python -m src.main --no-sms        # run but skip SMS
    python -m src.main --limit 5       # cap sources (debugging)
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from . import config
from .dedup import load_state, new_jobs, prune, save_state, update_state
from .filters import apply_filters
from .models import Job
from .notify import email as email_notify
from .notify import sms as sms_notify
from .sources.base import Source, make_session
from .sources.registry import build_all_sources

log = logging.getLogger("intern_pos_emailer")


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def collect_from(sources: list[Source], workers: int = 1) -> list[Job]:
    """Fetch every source, `workers` at a time. Result order follows `sources`.

    Fetching 38 sources one after another took ~42 s of a ~65 s run; the slow
    ones (Workday pagination) dominate, so running them side by side brings the
    whole collection down to roughly the slowest single source. Each thread
    gets its own requests.Session — Session is not guaranteed thread-safe.
    """
    if workers <= 1 or len(sources) <= 1:
        session = make_session()
        return [j for src in sources for j in src.safe_fetch(session)]

    local = threading.local()

    def _fetch(src: Source) -> list[Job]:
        if not hasattr(local, "session"):
            local.session = make_session()
        return src.safe_fetch(local.session)

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="fetch") as pool:
        return [j for batch in pool.map(_fetch, sources) for j in batch]


def collect_jobs(limit: int | None = None) -> list[Job]:
    sources = build_all_sources()
    if limit:
        sources = sources[:limit]
    workers = int(config.settings().get("http", {}).get("concurrency", 1) or 1)
    all_jobs = collect_from(sources, workers)
    log.info("collected %d raw jobs from %d sources (%d workers)", len(all_jobs), len(sources), workers)
    return all_jobs


def _print_digest(jobs: list[Job]) -> None:
    order = config.settings().get("email", {}).get(
        "category_order", ["swe", "quant", "consulting", "other"]
    )
    grouped = email_notify.group_by_category(jobs, order)
    print("\n" + "=" * 70)
    print(f"  {len(jobs)} NEW matching internship(s)")
    print("=" * 70)
    for cat, group in grouped:
        label = email_notify._CATEGORY_LABELS.get(cat, cat)
        print(f"\n{label} ({len(group)})")
        for j in sorted(group, key=lambda x: (x.company.lower(), x.title.lower())):
            loc = j.location_str or "—"
            print(f"  • {j.title} — {j.company}  [{loc}]")
            print(f"      {j.url}")
    print()


def run_test_notify() -> int:
    secrets = config.secrets()
    settings = config.settings()
    sample = Job(
        company="Example Corp",
        title="Software Engineer Intern (Summer 2027)",
        url="https://example.com/jobs/swe-intern",
        locations=["New York, NY"],
        category="swe",
        season="summer",
        year=2027,
    )
    sent_email = email_notify.send_email([sample], secrets, settings.get("email", {}))
    sms_cfg = settings.get("sms", {})
    sent_sms = False
    if sms_cfg.get("enabled", False):
        body = sms_notify.build_body(1, sms_cfg.get("template", "{n} new internships"))
        sent_sms = sms_notify.send_sms(f"[TEST] {body}", secrets)
    log.info("test-notify: email=%s sms=%s", sent_email, sent_sms)
    return 0 if (sent_email or sent_sms) else 1


def run(dry_run: bool, do_email: bool, do_sms: bool, limit: int | None, seed: bool = False) -> int:
    settings = config.settings()
    secrets = config.secrets()
    today = datetime.now().date()

    raw = collect_jobs(limit=limit)
    matched = apply_filters(raw)
    log.info("%d jobs passed filters", len(matched))

    state = load_state(config.state_path())

    if seed:
        # Mark everything currently open as already-seen, send nothing. Use this
        # once on first deploy so you only get *new* postings from then on.
        before = len(state)
        state = update_state(state, matched, today)
        state = prune(state, settings.get("prune_after_days", 120), today)
        save_state(config.state_path(), state)
        log.info("seeded %d jobs as seen (state %d -> %d); no notifications sent",
                 len(matched), before, len(state))
        return 0

    fresh = new_jobs(matched, state)
    log.info("%d are new (not previously seen)", len(fresh))

    if dry_run:
        _print_digest(fresh)
        log.info("dry-run: no notifications sent, state not modified")
        return 0

    suppress_empty = settings.get("suppress_when_empty", True)
    if not fresh and suppress_empty:
        log.info("no new jobs — nothing to send (suppress_when_empty=true)")
        # still persist pruned state so the file stays tidy
        state = prune(state, settings.get("prune_after_days", 120), today)
        save_state(config.state_path(), state)
        return 0

    delivered = True
    if fresh:
        email_cfg = settings.get("email", {})
        sms_cfg = settings.get("sms", {})
        if do_email and email_cfg.get("enabled", True):
            delivered = email_notify.send_email(fresh, secrets, email_cfg)
        if do_sms and sms_cfg.get("enabled", True) and len(fresh) >= sms_cfg.get("min_jobs", 1):
            body = sms_notify.build_body(len(fresh), sms_cfg.get("template", "{n} new internships"))
            sms_notify.send_sms(body, secrets)

    if not delivered:
        # send_email swallows SMTP errors (and missing creds) and returns False.
        # Recording these jobs as seen anyway would drop them permanently — they
        # would never be "new" again. Leave them unseen and exit non-zero so the
        # run goes red and the next one re-sends them.
        log.error("email delivery failed; leaving %d job(s) unseen for the next run", len(fresh))
        state = prune(state, settings.get("prune_after_days", 120), today)
        save_state(config.state_path(), state)
        return 1

    # Persist: record the new jobs as seen, prune old entries.
    state = update_state(state, fresh, today)
    state = prune(state, settings.get("prune_after_days", 120), today)
    save_state(config.state_path(), state)
    log.info("state saved (%d total tracked jobs)", len(state))
    return 0


def main(argv: list[str] | None = None) -> int:
    _setup_logging()
    parser = argparse.ArgumentParser(description="Daily internship scraper + notifier")
    parser.add_argument("--dry-run", action="store_true", help="fetch+filter, print, do not send or save")
    parser.add_argument("--seed", action="store_true", help="mark all current matches as seen without sending (run once on first deploy)")
    parser.add_argument("--test-notify", action="store_true", help="send a sample email+SMS to verify creds")
    parser.add_argument("--no-email", action="store_true", help="skip email this run")
    parser.add_argument("--no-sms", action="store_true", help="skip SMS this run")
    parser.add_argument("--limit", type=int, default=None, help="cap number of sources (debug)")
    args = parser.parse_args(argv)

    if args.test_notify:
        return run_test_notify()
    return run(
        dry_run=args.dry_run,
        do_email=not args.no_email,
        do_sms=not args.no_sms,
        limit=args.limit,
        seed=args.seed,
    )


if __name__ == "__main__":
    sys.exit(main())
