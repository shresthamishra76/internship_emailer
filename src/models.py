"""Core data models."""

from __future__ import annotations

import hashlib
import re
from datetime import date
from typing import Optional
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

# Categories a job can be classified into (set during filtering).
Category = str  # one of: "swe", "quant", "consulting", "other"


def normalize_title(title: str) -> str:
    """Lowercase + collapse whitespace, for stable IDs and matching."""
    return re.sub(r"\s+", " ", (title or "").strip().lower())


# Workday posting slugs end in `_R56028` (the requisition) or `_R56028-1`
# (the N-th posting of that requisition, e.g. the same req on the University
# site and the External site). Same req == same job, so the suffix is dropped.
_WORKDAY_POSTING_RE = re.compile(r"^(.*_[A-Za-z]*\d+)-\d+$")


def canonical_url(url: str) -> str:
    """Normalize a posting URL so the same listing hashes the same everywhere.

    Aggregators decorate URLs differently (utm params, trailing slashes, host
    case) while pointing at one posting. Scheme and host are lowercased; query
    and fragment are dropped; a trailing slash is stripped. On Workday hosts the
    per-site posting suffix is collapsed onto the requisition id.
    """
    raw = (url or "").strip()
    if not raw:
        return ""
    parts = urlsplit(raw)
    if not parts.netloc:
        return raw.rstrip("/")
    path = parts.path.rstrip("/")
    host = parts.netloc.lower()
    if host.endswith("myworkdayjobs.com"):
        m = _WORKDAY_POSTING_RE.match(path)
        if m:
            path = m.group(1)
    return f"{parts.scheme.lower()}://{host}{path}"


def job_id_for(company: str, title: str, url: str) -> str:
    """Stable dedup id. Keyed on the canonical URL alone when one exists.

    Company and title must not participate: the same posting reaches us via
    several aggregators that label the company differently ("Cadence",
    "Cadence (University)", "Cadence Design Systems") and truncate or rewrite
    titles, and each spelling drift used to mint a fresh id -> a repeat alert.
    Company + title is the fallback only for listings without a URL.
    """
    canon = canonical_url(url)
    basis = canon if canon else f"{(company or '').strip().lower()}|{normalize_title(title)}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


class Job(BaseModel):
    """A normalized job posting from any source."""

    company: str
    title: str
    url: str
    locations: list[str] = Field(default_factory=list)
    source: str = ""  # e.g. "simplify-summer", "greenhouse:Stripe"
    ats: Optional[str] = None  # greenhouse | lever | ashby | workday | github-list

    # Filled in by the filter step.
    category: Optional[Category] = None
    season: Optional[str] = None  # summer | spring | fall | winter | offcycle
    year: Optional[int] = None

    # Optional metadata when the source provides it.
    posted_date: Optional[str] = None  # ISO date string when known
    sponsorship: Optional[str] = None
    active: bool = True

    @property
    def location_str(self) -> str:
        return " | ".join(self.locations) if self.locations else ""

    @property
    def job_id(self) -> str:
        """Stable id used for dedup. See `job_id_for`."""
        return job_id_for(self.company, self.title, self.url)


class ApplicantProfile(BaseModel):
    """Stored applicant info for the (future) auto-apply module.

    Loaded from config/profile.yaml (gitignored if it holds real data).
    Nothing here is used by the notify pipeline today — it exists so the
    auto-apply module has a stable contract to build against.
    """

    full_name: str = ""
    email: str = ""
    phone: str = ""
    school: str = ""
    graduation_date: str = ""  # e.g. "2027-05"
    gpa: str = ""
    current_location: str = ""  # e.g. "Boston, MA"
    work_authorization: str = ""  # e.g. "US Citizen", "Need sponsorship"
    requires_sponsorship: Optional[bool] = None
    linkedin: str = ""
    github: str = ""
    website: str = ""
    resume_path: str = ""  # local path to resume PDF (gitignored)
    # A few sentences about your background/skills — used to ground the
    # AI-generated cover letter so it reflects real experience, not invention.
    summary: str = ""
    # Common screening questions -> canned answers, e.g.
    #   {"Are you authorized to work in the US?": "Yes"}
    common_answers: dict[str, str] = Field(default_factory=dict)

    @property
    def is_configured(self) -> bool:
        """Minimum needed to attempt an application."""
        return bool(self.full_name and self.email and self.resume_path)
