"""Email digest via Gmail SMTP (App Password)."""

from __future__ import annotations

import logging
import re
import smtplib
import ssl
from email.message import EmailMessage
from html import escape

from ..models import Job

log = logging.getLogger(__name__)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465

_CATEGORY_LABELS = {
    "swe": "💻 Software Engineering",
    "ai": "🤖 AI / Machine Learning",
    "quant": "📈 Quant / Trading",
    "consulting": "📊 Consulting",
    "other": "🧩 Other",
}


def is_faang(company: str, terms: list[str]) -> bool:
    """Token-based match so 'apple' hits 'Apple Inc' but not 'Snapple'."""
    tokens = set(re.findall(r"[a-z0-9]+", (company or "").lower()))
    return any(t in tokens for t in terms)


def faang_jobs(jobs: list[Job], terms: list[str]) -> list[Job]:
    terms = [t.lower() for t in (terms or [])]
    if not terms:
        return []
    return [j for j in jobs if is_faang(j.company, terms)]


def group_by_category(jobs: list[Job], order: list[str]) -> list[tuple[str, list[Job]]]:
    buckets: dict[str, list[Job]] = {}
    for j in jobs:
        buckets.setdefault(j.category or "other", []).append(j)
    ordered_keys = [c for c in order if c in buckets]
    ordered_keys += [c for c in buckets if c not in order]
    return [(c, buckets[c]) for c in ordered_keys]


def _counts_summary(grouped: list[tuple[str, list[Job]]]) -> str:
    parts = []
    for cat, jobs in grouped:
        label = _CATEGORY_LABELS.get(cat, cat).split(" ", 1)[-1]
        parts.append(f"{len(jobs)} {label}")
    return ", ".join(parts)


def build_subject(jobs: list[Job], grouped, prefix: str, faang: list[Job] | None = None) -> str:
    if faang:
        names = ", ".join(sorted({j.company for j in faang}))
        return f"🚨 FAANG job out now — {names} ({len(jobs)} new internship(s))"
    return f"{prefix} {len(jobs)} new internship(s) — {_counts_summary(grouped)}"


def _faang_banner(faang: list[Job]) -> str:
    items = []
    for j in sorted(faang, key=lambda x: (x.company.lower(), x.title.lower())):
        loc = escape(j.location_str) if j.location_str else ""
        items.append(
            "<li style='margin:6px 0'>"
            f"<b style='color:#7f1d1d'>{escape(j.company)}</b> — "
            f"<a href='{escape(j.url)}' style='color:#b91c1c;font-weight:700;"
            f"text-decoration:none'>{escape(j.title)}</a>"
            + (f"<span style='color:#9f6b6b;font-size:12px'> · {loc}</span>" if loc else "")
            + "</li>"
        )
    return (
        "<div style='background:#fff1f0;border:2px solid #e11d48;border-radius:8px;"
        "padding:14px 16px;margin:14px 0'>"
        "<div style='font:700 17px system-ui,sans-serif;color:#b91c1c;margin-bottom:6px'>"
        "🚨 FAANG roles just posted — apply now</div>"
        f"<ul style='margin:0;padding-left:20px;font:14px system-ui,sans-serif'>{''.join(items)}</ul>"
        "</div>"
    )


_FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"


def by_company(jobs: list[Job]) -> list[tuple[str, list[Job]]]:
    """Group a category's jobs under their company, companies A-Z."""
    buckets: dict[str, list[Job]] = {}
    for j in jobs:
        buckets.setdefault(j.company, []).append(j)
    return [
        (c, sorted(buckets[c], key=lambda x: x.title.lower()))
        for c in sorted(buckets, key=str.lower)
    ]


def _job_line(j: Job) -> str:
    """One role: the title is the link, the metadata sits quietly underneath."""
    meta_bits = [b for b in (j.location_str, j.season, str(j.year) if j.year else None) if b]
    meta = escape(" · ".join(meta_bits))
    meta_html = (
        f"<div style='font:12px {_FONT};color:#64748b;margin-top:2px'>{meta}</div>"
        if meta else ""
    )
    return (
        "<div style='margin:0 0 10px'>"
        f"<a href='{escape(j.url)}' style='font:600 14px {_FONT};color:#1d4ed8;"
        f"text-decoration:none'>{escape(j.title)}</a>"
        f"{meta_html}"
        "</div>"
    )


def build_html(grouped: list[tuple[str, list[Job]]], total: int, faang: list[Job] | None = None) -> str:
    headline = "🚨 FAANG job out now" if faang else "🚀 Internship Digest"
    rows = []
    if faang:
        rows.append(_faang_banner(faang))

    counts = " · ".join(
        f"{len(jobs)} {_CATEGORY_LABELS.get(cat, cat).split(' ', 1)[-1]}"
        for cat, jobs in grouped
    )
    rows.append(
        f"<p style='font:14px {_FONT};color:#334155;margin:4px 0 20px'>"
        f"<b style='color:#0f172a'>{total}</b> new posting(s) — {escape(counts)}</p>"
    )

    for cat, jobs in grouped:
        label = _CATEGORY_LABELS.get(cat, cat)
        rows.append(
            f"<div style='font:700 13px {_FONT};color:#0f172a;letter-spacing:.06em;"
            f"text-transform:uppercase;margin:28px 0 10px;padding-bottom:6px;"
            f"border-bottom:2px solid #0f172a'>{escape(label)} ({len(jobs)})</div>"
        )
        # Company first: it is the thing you scan for, so it gets the weight and
        # its roles nest under it rather than repeating the name on every line.
        for company, roles in by_company(jobs):
            suffix = f" <span style='color:#64748b;font-weight:400'>({len(roles)} roles)</span>" if len(roles) > 1 else ""
            rows.append(
                "<div style='margin:0 0 14px;padding:12px 14px;background:#f8fafc;"
                "border:1px solid #e2e8f0;border-left:3px solid #1d4ed8;border-radius:6px'>"
                f"<div style='font:700 15px {_FONT};color:#0f172a;margin-bottom:8px'>"
                f"{escape(company)}{suffix}</div>"
                + "".join(_job_line(j) for j in roles)
                + "</div>"
            )

    body = "".join(rows)
    return (
        "<div style='max-width:680px;margin:0 auto;padding:8px'>"
        f"<h1 style='font:700 20px {_FONT};color:#0f172a;margin:0 0 2px'>"
        f"{escape(headline)}</h1>"
        f"{body}"
        f"<p style='font:12px {_FONT};color:#94a3b8;margin-top:32px;"
        "border-top:1px solid #e2e8f0;padding-top:12px'>"
        "Generated by intern_pos_emailer · tune sources and filters in <code>config/</code></p>"
        "</div>"
    )


def build_text(grouped: list[tuple[str, list[Job]]], total: int, faang: list[Job] | None = None) -> str:
    lines = []
    if faang:
        lines.append("*** FAANG JOB OUT NOW ***")
        for j in sorted(faang, key=lambda x: (x.company.lower(), x.title.lower())):
            lines.append(f"  -> {j.title} — {j.company}  {j.url}")
        lines.append("")
    lines += [f"{total} new internship posting(s):", ""]
    for cat, jobs in grouped:
        lines.append(f"== {_CATEGORY_LABELS.get(cat, cat)} ({len(jobs)}) ==")
        # Mirrors the HTML: company heading, roles nested beneath it.
        for company, roles in by_company(jobs):
            lines.append(f"\n  {company.upper()}")
            for j in roles:
                meta = " · ".join(
                    b for b in (j.location_str, j.season, str(j.year) if j.year else None) if b
                )
                lines.append(f"    - {j.title}" + (f"  [{meta}]" if meta else ""))
                lines.append(f"      {j.url}")
        lines.append("")
    return "\n".join(lines)


def send_email(
    jobs: list[Job],
    secrets: dict[str, str],
    email_cfg: dict,
    *,
    subject_override: str | None = None,
    html_override: str | None = None,
    text_override: str | None = None,
) -> bool:
    """Send the digest. Returns True if sent, False if skipped (missing creds)."""
    user = secrets.get("GMAIL_USER")
    password = secrets.get("GMAIL_APP_PASSWORD")
    to = secrets.get("EMAIL_TO") or user
    if not (user and password and to):
        log.warning("email skipped: GMAIL_USER / GMAIL_APP_PASSWORD / EMAIL_TO not all set")
        return False

    order = email_cfg.get("category_order", ["swe", "quant", "consulting", "other"])
    grouped = group_by_category(jobs, order)
    faang = faang_jobs(jobs, email_cfg.get("faang_companies", []))
    subject = subject_override or build_subject(
        jobs, grouped, email_cfg.get("subject_prefix", "[Intern Alert]"), faang
    )
    html = html_override or build_html(grouped, len(jobs), faang)
    text = text_override or build_text(grouped, len(jobs), faang)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = user
    recipients = [addr.strip() for addr in to.split(",") if addr.strip()]
    msg["To"] = ", ".join(recipients)
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    context = ssl.create_default_context()
    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context) as server:
            server.login(user, password)
            server.send_message(msg, from_addr=user, to_addrs=recipients)
        log.info("email sent to %s (%d jobs)", recipients, len(jobs))
        return True
    except Exception as exc:  # noqa: BLE001
        log.error("email send failed: %s", exc)
        return False
