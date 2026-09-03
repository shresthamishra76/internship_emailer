"""internship_terms must match whole words, not substrings."""

from src.filters import _contains_word

TERMS = ["intern", "internship", "co-op", "coop", "co op", "summer analyst", "student"]


def test_matches_real_internship_titles():
    for t in [
        "software engineer intern",
        "software engineering interns (summer 2027)",
        "software engineer internship, android",
        "swe co-op",
        "engineering coop - fall",
        "co op software developer",
        "2027 summer analyst - technology",
        "student software developer",
        "intern: platform",
    ]:
        assert _contains_word(t, TERMS), t


def test_rejects_substring_lookalikes():
    for t in [
        "software engineer, internal applications - enterprise",
        "software engineer, international",
        "software engineer, backend (cooperative ai)",
        "internet infrastructure engineer",
        "studentship coordinator",  # not "student" as a word
    ]:
        assert not _contains_word(t, TERMS), t
