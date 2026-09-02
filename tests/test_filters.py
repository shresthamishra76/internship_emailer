"""Filter behaviour against the real config/filters.yaml."""

from src import config
from src.filters import passes
from src.models import Job


def _job(title, locations=None, **kw):
    return Job(
        company=kw.pop("company", "Acme"),
        title=title,
        url=kw.pop("url", f"https://example.com/{abs(hash(title)) % 10000}"),
        locations=locations or [],
        **kw,
    )


F = config.filters()


def test_swe_summer_intern_us_kept():
    j = _job("Software Engineer Intern", ["New York, NY"])
    assert passes(j, F)
    assert j.category == "swe"
    assert j.season == "summer" or j.season is None  # season may be undetected from title


def test_quant_intern_classified_as_quant():
    j = _job("Quantitative Trading Intern", ["Chicago, IL"])
    assert passes(j, F)
    assert j.category == "quant"


def test_consulting_intern_rejected():
    # The consulting group is commented out in config/filters.yaml, and
    # require_category is on, so a consulting-only title matches nothing and
    # is dropped. Flip this back to the "kept" assertion if that group returns.
    j = _job("Technology Analyst Intern", ["Boston, MA"])
    assert not passes(j, F)


def test_fulltime_senior_role_rejected():
    j = _job("Senior Software Engineer", ["San Francisco, CA"])
    assert not passes(j, F)


def test_new_grad_fulltime_rejected():
    j = _job("Software Engineer, New Grad", ["Seattle, WA"])
    # no internship term -> rejected
    assert not passes(j, F)


def test_non_us_location_rejected():
    j = _job("Software Engineer Intern", ["London, UK"])
    assert not passes(j, F)


def test_canada_rejected():
    j = _job("Software Developer Intern", ["Toronto, Canada"])
    assert not passes(j, F)


def test_unknown_location_kept():
    j = _job("Software Engineer Intern")
    assert passes(j, F)  # keep_when_location_unknown: true


def test_multi_location_with_us_option_kept():
    j = _job("Software Engineer Intern", ["London, UK", "New York, NY"])
    assert passes(j, F)


def test_non_category_intern_rejected():
    j = _job("Marketing Intern", ["New York, NY"])
    assert not passes(j, F)


def test_out_of_window_year_rejected():
    j = _job("Software Engineer Intern, Summer 2025", ["Austin, TX"])
    assert not passes(j, F)


def test_coop_kept():
    j = _job("Software Engineering Co-op", ["Boston, MA"])
    assert passes(j, F)


def test_remote_kept():
    j = _job("Software Engineer Intern", ["Remote"])
    assert passes(j, F)
