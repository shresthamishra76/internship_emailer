

# --- commit pinning ---------------------------------------------------------

from src.sources.github_lists import pin_raw_url, split_raw_url  # noqa: E402

_RAW = "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/.github/scripts/listings.json"
_SHA = "f191ac87fbb11e6eb8f131ce7fc6bf79d0602e04"


class _Resp:
    def __init__(self, status, text):
        self.status_code, self.text = status, text


class _Session:
    def __init__(self, resp=None, exc=None):
        self.resp, self.exc, self.calls = resp, exc, []

    def get(self, url, **kw):
        self.calls.append(url)
        if self.exc:
            raise self.exc
        return self.resp


def test_split_raw_url():
    assert split_raw_url(_RAW) == (
        "SimplifyJobs", "Summer2027-Internships", "dev", ".github/scripts/listings.json"
    )
    assert split_raw_url("https://example.com/x.json") is None


def test_pin_raw_url_rewrites_branch_to_sha():
    s = _Session(_Resp(200, _SHA + "\n"))
    out = pin_raw_url(s, _RAW)
    assert out == _RAW.replace("/dev/", f"/{_SHA}/")
    assert s.calls == ["https://api.github.com/repos/SimplifyJobs/Summer2027-Internships/commits/dev"]


def test_pin_raw_url_leaves_sha_and_foreign_urls_alone():
    s = _Session(_Resp(200, _SHA))
    pinned = _RAW.replace("/dev/", f"/{_SHA}/")
    assert pin_raw_url(s, pinned) == pinned
    assert pin_raw_url(s, "https://example.com/x.json") == "https://example.com/x.json"
    assert s.calls == []


def test_pin_raw_url_falls_back_on_api_failure():
    assert pin_raw_url(_Session(_Resp(403, "rate limited")), _RAW) == _RAW
    assert pin_raw_url(_Session(exc=OSError("boom")), _RAW) == _RAW
