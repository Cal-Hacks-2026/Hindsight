import httpx
import pytest

from app.services.assist import AssistClient, AssistError, AssistNotFound
from tests.assist_fake import DS_KEY, FakeAssist


def make() -> tuple[AssistClient, FakeAssist]:
    fake = FakeAssist()
    return AssistClient(transport=httpx.MockTransport(fake)), fake


def test_handshake_then_token_header_on_every_call():
    client, fake = make()
    client.institutions()
    client.institutions()
    assert fake.count("/") == 1
    api = [r for r in fake.requests if r.url.path.startswith("/api/")]
    assert [r.headers["X-XSRF-TOKEN"] for r in api] == ["tok-1", "tok-1"]
    assert "Mozilla" in fake.requests[0].headers["User-Agent"]


def test_stale_token_rehandshakes_once_and_retries():
    client, fake = make()
    client.institutions()
    fake.rotate()
    assert client.institutions()
    assert fake.count("/") == 2


def test_no_xsrf_cookie_is_an_error():
    client = AssistClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="")))
    with pytest.raises(AssistError, match="X-XSRF-TOKEN"):
        client.institutions()


def test_institution_lookup_is_exact():
    client, _ = make()
    assert client.institution_id("University of California, Berkeley") == 79
    assert client.institution_id("san jose state university") == 39
    with pytest.raises(AssistNotFound):
        client.institution_id("Berkeley")  # "Berkeley City College" must not match


def test_partner_year_ids():
    client, _ = make()
    assert client.partner_year_ids(113, 39) == [75, 76, 77]
    assert client.partner_year_ids(113, 1) == []


def test_major_label_must_match_exactly():
    client, _ = make()
    assert client.major(113, 39, 77, "Data Science, B.S.")["key"] == DS_KEY
    labels = [m["label"] for m in client.majors(113, 39, 77)]
    assert "Public Health, Concentration in Population Data Science, B.S." in labels
    with pytest.raises(AssistNotFound):
        client.major(113, 39, 77, "Data Science")


def test_agreement_fetch_and_unknown_key():
    client, fake = make()
    result = client.agreement(DS_KEY)
    assert result["name"] == "Data Science, B.S."
    assert isinstance(result["templateAssets"], str)  # still double-encoded; parser decodes
    with pytest.raises(AssistNotFound, match="not found"):
        client.agreement("77/113/to/39/Major/nope")
    assert fake.count("/") == 1  # a validation 400 is not mistaken for a stale token
