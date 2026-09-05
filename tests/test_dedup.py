"""Dedup / state behaviour."""

from datetime import date

from src import dedup
from src.models import Job


def _job(company, title, url):
    return Job(company=company, title=title, url=url)


def test_new_jobs_excludes_seen():
    j1 = _job("Acme", "SWE Intern", "https://a.com/1")
    j2 = _job("Beta", "Quant Intern", "https://b.com/2")
    state = {j1.job_id: {"first_seen": "2026-06-01"}}
    out = dedup.new_jobs([j1, j2], state)
    assert out == [j2]


def test_new_jobs_dedups_within_batch():
    j1 = _job("Acme", "SWE Intern", "https://a.com/1")
    dup = _job("Acme", "SWE Intern", "https://a.com/1")  # same id
    out = dedup.new_jobs([j1, dup], {})
    assert len(out) == 1


def test_update_state_adds_entries():
    j = _job("Acme", "SWE Intern", "https://a.com/1")
    state: dict = {}
    dedup.update_state(state, [j], today=date(2026, 6, 22))
    assert j.job_id in state
    assert state[j.job_id]["first_seen"] == "2026-06-22"
    assert state[j.job_id]["company"] == "Acme"


def test_prune_removes_old_entries():
    state = {
        "old": {"first_seen": "2025-01-01"},
        "recent": {"first_seen": "2026-06-20"},
    }
    kept = dedup.prune(state, max_age_days=120, today=date(2026, 6, 22))
    assert "recent" in kept
    assert "old" not in kept


def test_prune_noop_when_disabled():
    state = {"old": {"first_seen": "2000-01-01"}}
    kept = dedup.prune(state, max_age_days=0, today=date(2026, 6, 22))
    assert kept == state


def test_job_id_stable_and_case_insensitive():
    a = _job("Acme", "SWE Intern", "https://a.com/1")
    b = _job("acme", "swe  intern", "https://a.com/1")  # case + extra space
    assert a.job_id == b.job_id


def _src_job(company, title, url, source):
    return Job(company=company, title=title, url=url, source=source)


def test_new_jobs_skips_role_already_notified_under_other_url():
    old = _job("Acme", "SWE Intern", "https://a.com/1")
    state = {old.job_id: {"first_seen": "2026-06-01", "company": "Acme", "title": "SWE Intern"}}
    relisted = _job("acme", "swe intern", "https://jobs.acme.com/relisted")
    assert dedup.new_jobs([relisted], state) == []


def test_new_jobs_collapses_same_role_across_sources():
    a = _src_job("Acme", "SWE Intern", "https://a.com/1?utm=simplify", "githublist:simplify")
    b = _src_job("Acme", "SWE Intern", "https://a.com/1", "githublist:zapply")
    out = dedup.new_jobs([a, b], {})
    assert out == [a]


def test_new_jobs_keeps_same_role_from_one_source():
    # Same title, different reqs (sites/teams) from a single source stay separate.
    a = _src_job("Acme", "SWE Intern", "https://a.com/boston", "greenhouse")
    b = _src_job("Acme", "SWE Intern", "https://a.com/austin", "greenhouse")
    assert dedup.new_jobs([a, b], {}) == [a, b]


# --- URL-keyed ids (regression: Cadence R56028/R56029 re-alerted 3x, Sep 2026) ---

from src.models import canonical_url, job_id_for

_CAD = "https://cadence.wd1.myworkdayjobs.com/External_Careers/job/AUSTIN/Graduate-Student-Intern---Software-Engineering_R56029-2"


def test_job_id_ignores_company_and_title_when_url_present():
    a = _job("Cadence", "Graduate Student Intern - Software En", _CAD)
    b = _job("Cadence Design Systems", "Software Engineering Intern", _CAD)
    c = _job("Cadence", "Graduate Student Intern - Software Engineering", _CAD)
    assert a.job_id == b.job_id == c.job_id


def test_job_id_strips_query_fragment_trailing_slash_and_host_case():
    base = _job("Acme", "SWE Intern", "https://jobs.acme.com/x/1")
    assert _job("Acme", "SWE Intern", "https://JOBS.acme.com/x/1/?utm_source=Simplify#top").job_id == base.job_id


def test_job_id_collapses_workday_posting_suffix_across_sites():
    univ = "https://cadence.wd1.myworkdayjobs.com/Univ_Careers/job/AUSTIN/Graduate-Student-Intern---Software-Engineering_R56028"
    ext = "https://cadence.wd1.myworkdayjobs.com/External_Careers/job/AUSTIN/Graduate-Student-Intern---Software-Engineering_R56028-1"
    # The `-N` posting suffix is dropped so re-postings of one requisition on
    # the same site share an id. Different sites keep distinct ids: the site
    # prefix is part of the path.
    assert canonical_url(ext).endswith("_R56028")
    assert canonical_url(ext) == canonical_url(ext.removesuffix("-1") + "-3")
    assert canonical_url(univ) != canonical_url(ext)


def test_job_id_falls_back_to_company_title_without_url():
    assert job_id_for("Acme", "SWE  Intern", "") == job_id_for("acme", "swe intern", "")
    assert job_id_for("Acme", "SWE Intern", "") != job_id_for("Acme", "Quant Intern", "")


def test_relabeled_listing_is_not_new():
    seen = _job("Cadence", "Graduate Student Intern - Software En", _CAD)
    state = {seen.job_id: {"first_seen": "2026-09-02", "company": "Cadence",
                           "title": "Graduate Student Intern - Software En", "url": _CAD}}
    relabeled = _job("Cadence Design Systems", "Software Engineering Intern", _CAD + "?utm_source=Simplify")
    assert dedup.new_jobs([relabeled], state) == []


def test_load_state_migrates_legacy_keys(tmp_path):
    import json
    legacy_a = {"first_seen": "2026-09-02", "company": "Cadence", "title": "Graduate Student Intern - Software En", "url": _CAD}
    legacy_b = {"first_seen": "2026-09-05", "company": "Cadence", "title": "Graduate Student Intern - Software Engineering", "url": _CAD}
    other = {"first_seen": "2026-08-01", "company": "Beta", "title": "Quant Intern", "url": "https://b.com/2"}
    path = tmp_path / "seen.json"
    path.write_text(json.dumps({"oldkey-a": legacy_a, "oldkey-b": legacy_b, "oldkey-c": other}))
    state = dedup.load_state(path)
    new_id = job_id_for("", "", _CAD)
    assert set(state) == {new_id, job_id_for("", "", "https://b.com/2")}
    assert state[new_id]["first_seen"] == "2026-09-02"  # earliest wins
    # idempotent
    dedup.save_state(path, state)
    assert dedup.load_state(path) == state
