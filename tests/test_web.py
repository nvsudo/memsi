from fastapi.testclient import TestClient

from memsi.web.app import create_app
from tests.conftest import approve


def client(svc):
    return TestClient(create_app(svc))


def test_inbox_shows_pending_with_neighbours_and_approves(svc):
    old = approve(svc, "Lives in Melbourne.", type="fact", scope="personal", subject="home-city")
    r = svc.propose("Moved to Sydney.", type="fact", scope="personal", subject="home-city", source_app="claude-desktop")
    c = client(svc)
    html = c.get("/inbox").text
    assert "Moved to Sydney." in html and "possible update" in html and "Lives in Melbourne." in html
    resp = c.post(f"/inbox/{r.memory.id}/decide", data={"action": "supersede", "supersedes_id": old.id, "quote": "yes moved"}, follow_redirects=False)
    assert resp.status_code == 303
    assert svc.get(r.memory.id).status == "approved"
    assert svc.get(old.id).status == "superseded"
    assert "Nothing pending" in c.get("/inbox").text


def test_inbox_edit_then_approve(svc):
    r = svc.propose("Likes coffe.", type="preference", scope="personal", source_app="claude-code", confidence=0.6)
    c = client(svc)
    c.post(f"/inbox/{r.memory.id}/decide", data={"action": "approve", "content": "Likes coffee.", "quote": ""})
    m = svc.get(r.memory.id)
    assert m.status == "approved" and m.content == "Likes coffee."
    assert [e.kind for e in svc.audit()][:2] == ["approved", "edited"]


def test_approve_clean_only_touches_items_without_neighbours(svc):
    approve(svc, "Lives in Melbourne.", type="fact", scope="personal", subject="home-city")
    conflicted = svc.propose("Moved to Sydney.", type="fact", scope="personal", subject="home-city", source_app="x")
    clean = svc.propose("Plays squash on Thursdays.", type="fact", scope="personal", source_app="x")
    client(svc).post("/inbox/approve-clean")
    assert svc.get(clean.memory.id).status == "approved"
    assert svc.get(conflicted.memory.id).status == "pending"


def test_digest_preview_renders_and_respects_app_filter(svc):
    approve(svc, "Lives in Melbourne.", type="fact", scope="personal", sensitivity="private")
    approve(svc, "Works at Redis.", type="identity", scope="work")
    c = client(svc)
    html = c.get("/digest").text
    assert "Melbourne" in html and "Works at Redis." in html and "## Identity" in html
    html2 = c.get("/digest", params={"app_name": "chatgpt"}).text
    assert "Melbourne" not in html2.split("<h3>Ranking</h3>")[0]
    j = c.get("/api/digest").json()
    assert j["included"] == 2 and j["used_tokens"] <= j["budget_tokens"]


def test_browse_timeline_health(svc):
    approve(svc, "Prefers tea.", type="preference", scope="personal")
    c = client(svc)
    assert "Prefers tea." in c.get("/browse").text
    assert "Prefers tea." in c.get("/browse", params={"q": "tea"}).text
    assert "approved" in c.get("/timeline").text
    assert c.get("/api/health").json()["items"] == 1
