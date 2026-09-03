"""Persisted state: which jobs have already been notified.

State file shape (data/seen_jobs.json):
    { "<job_id>": {"first_seen": "2026-06-22", "company": ..., "title": ..., "url": ...}, ... }
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

from .models import Job, normalize_title

log = logging.getLogger(__name__)


def load_state(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("could not read state %s: %s — starting fresh", path, exc)
        return {}


def save_state(path: Path, state: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2, sort_keys=True, ensure_ascii=False)
        fh.write("\n")


def _role_key(company: str, title: str) -> tuple[str, str]:
    return ((company or "").strip().lower(), normalize_title(title))


def new_jobs(jobs: list[Job], state: dict[str, dict]) -> list[Job]:
    """Jobs not already notified.

    Primary key is job_id (company + title + url). A second, looser key of
    company + title catches the same role reaching us through two aggregators
    with different URLs, or re-listed under a fresh URL: it is skipped if that
    role was already notified (present in state), or if another *source* in
    this batch already contributed it. Same-source rows sharing a title are
    kept — those are usually distinct reqs (different sites/teams).
    """
    seen_ids: set[str] = set()
    notified_roles = {
        _role_key(meta.get("company", ""), meta.get("title", ""))
        for meta in state.values()
        if isinstance(meta, dict)
    }
    batch_roles: dict[tuple[str, str], str] = {}
    out: list[Job] = []
    for job in jobs:
        jid = job.job_id
        if jid in state or jid in seen_ids:
            continue
        role = _role_key(job.company, job.title)
        if role in notified_roles:
            log.debug("skip %s @ %s: role already notified under another url", job.title, job.company)
            continue
        first_src = batch_roles.get(role)
        if first_src is not None and first_src != job.source:
            log.debug("skip %s @ %s: same role already in batch from %s", job.title, job.company, first_src)
            continue
        batch_roles.setdefault(role, job.source)
        seen_ids.add(jid)
        out.append(job)
    return out


def update_state(
    state: dict[str, dict], jobs: list[Job], today: date | None = None
) -> dict[str, dict]:
    today = today or datetime.now().date()
    iso = today.isoformat()
    for job in jobs:
        state[job.job_id] = {
            "first_seen": iso,
            "company": job.company,
            "title": job.title,
            "url": job.url,
        }
    return state


def prune(
    state: dict[str, dict], max_age_days: int, today: date | None = None
) -> dict[str, dict]:
    if not max_age_days or max_age_days <= 0:
        return state
    today = today or datetime.now().date()
    cutoff = today - timedelta(days=max_age_days)
    kept: dict[str, dict] = {}
    for jid, meta in state.items():
        fs = meta.get("first_seen")
        try:
            seen_date = date.fromisoformat(fs) if fs else today
        except ValueError:
            seen_date = today
        if seen_date >= cutoff:
            kept[jid] = meta
    removed = len(state) - len(kept)
    if removed:
        log.info("pruned %d stale state entries (> %d days)", removed, max_age_days)
    return kept
