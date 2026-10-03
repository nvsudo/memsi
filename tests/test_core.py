import time

from memsi.backend import Filters
from tests.conftest import approve


def test_propose_lands_pending(svc):
    r = svc.propose("Lives in Melbourne.", type="fact", scope="personal", subject="home-city", source_app="claude-desktop")
    assert r.status == "pending"
    assert r.memory.status == "pending"
    assert r.neighbours == []
    assert svc.recall().text.count("Melbourne") == 0, "pending must not appear in the digest"
    kinds = [e.kind for e in svc.audit()]
    assert kinds[0] == "proposed"


def test_confirm_approve_records_quote_and_enters_digest(svc):
    r = svc.propose("Prefers short, direct answers.", type="preference", scope="work", subject="communication-style", source_app="claude-code", confidence=0.7)
    m = svc.confirm(r.memory.id, "approve", user_quote="yes keep that", via="claude-code")
    assert m.status == "approved"
    assert m.approval.quote == "yes keep that"
    assert "Prefers short, direct answers." in svc.recall().text
    assert svc.audit()[0].kind == "approved"


def test_exact_duplicate_is_dropped(svc):
    approve(svc, "Prefers short, direct answers.", type="preference", scope="work")
    r = svc.propose("Prefers short, direct answers.", type="preference", scope="work", source_app="claude-desktop")
    assert r.status == "duplicate"
    assert r.duplicate_of is not None
    assert svc.backend.count(Filters(status=["pending"])) == 0


def test_same_subject_surfaces_possible_update_even_with_low_similarity(svc):
    old = approve(svc, "Lives in Melbourne.", type="fact", scope="personal", subject="home-city")
    r = svc.propose("Moved to Sydney in September 2026.", type="fact", scope="personal", subject="home-city", source_app="claude-desktop")
    assert r.status == "pending"
    rels = {n.memory.id: n.relation for n in r.neighbours}
    assert rels[old.id] == "possible_update"


def test_supersede_closes_old_and_removes_from_digest(svc):
    old = approve(svc, "Lives in Melbourne.", type="fact", scope="personal", subject="home-city")
    r = svc.propose("Lives in Sydney.", type="fact", scope="personal", subject="home-city", source_app="claude-desktop")
    new = svc.confirm(r.memory.id, "supersede", user_quote="yes, I moved", via="claude-desktop", supersedes_id=old.id)
    old2 = svc.get(old.id)
    assert new.status == "approved" and new.supersedes == old.id
    assert old2.status == "superseded" and old2.valid_to is not None and old2.superseded_by == new.id
    text = svc.recall().text
    assert "Sydney" in text and "Melbourne" not in text


def test_reject_and_retract(svc):
    r = svc.propose("Hates mornings.", type="preference", scope="personal", source_app="claude-code", confidence=0.5)
    assert svc.confirm(r.memory.id, "reject", user_quote="no", via="claude-code").status == "rejected"
    m = approve(svc, "Drinks oat milk.", type="fact", scope="personal")
    assert svc.retract(m.id, reason="wrong", via="cli").status == "retracted"
    assert "oat" not in svc.recall().text


def test_auto_approve_rule_respects_source_confidence_and_neighbours(svc):
    r = svc.propose("memsi dashboard runs on port 7677.", type="project", scope="project:memsi", source_app="claude-code", confidence=0.9)
    assert r.status == "auto_approved"
    r2 = svc.propose("Uses pytest for the memsi test suite.", type="project", scope="project:memsi", source_app="claude-desktop", confidence=0.9)
    assert r2.status == "pending", "wrong source must not auto-approve"
    r3 = svc.propose("Deploys memsi with uv.", type="project", scope="project:memsi", source_app="claude-code", confidence=0.6)
    assert r3.status == "pending", "low confidence must not auto-approve"


def test_identity_never_auto_approves(settings, svc):
    settings.auto_approve.append(type(settings.auto_approve[0])(type="identity", min_confidence=0.0, sources=[]))
    r = svc.propose("Is called Nik.", type="identity", scope="personal", source_app="claude-code", confidence=1.0)
    assert r.status == "pending"


def test_read_filter_hides_private_from_restricted_app(svc):
    approve(svc, "Lives in Melbourne.", type="fact", scope="personal", sensitivity="private")
    approve(svc, "Works at Redis.", type="identity", scope="work", sensitivity="internal")
    full = svc.recall().text
    chat = svc.recall(app="chatgpt").text
    assert "Melbourne" in full and "Redis" in full
    assert "Melbourne" not in chat and "Redis" in chat
    assert all(m.sensitivity != "private" for m, _ in svc.search("where does he live", app="chatgpt"))


def test_digest_respects_budget_and_ranks_identity_first(svc):
    approve(svc, "Is Nik, works at Redis.", type="identity", scope="work", confidence=0.99)
    topics = ["gardening", "chess", "sailing", "pottery", "jazz", "cycling", "baking", "astronomy", "hiking", "origami",
              "kayaking", "birdwatching", "calligraphy", "surfing", "knitting", "archery", "fencing", "beekeeping", "woodwork", "climbing"]
    for i, t in enumerate(topics):
        approve(svc, f"Took up {t} in {2000 + i} and still enjoys it on weekends.", type="fact", scope="personal", confidence=0.5)
        approve(svc, f"Owns a well used {t} kit stored in the garage.", type="fact", scope="personal", confidence=0.5)
    d = svc.recall(budget_tokens=300)
    assert d.used_tokens <= 300
    assert any(i.memory.type == "identity" for i in d.included)
    assert len(d.excluded) > 0
    assert d.text.index("## Identity") < d.text.index("## Facts")


def test_project_scope_included_only_when_requested(svc):
    approve(svc, "memsi uses Redis 8 JSON and Search.", type="project", scope="project:memsi")
    assert "memsi uses" not in svc.recall().text
    assert "memsi uses" in svc.recall(scope="project:memsi").text


def test_pending_expiry(svc):
    r = svc.propose("Old proposal nobody answered.", type="fact", scope="personal", source_app="x")
    m = svc.get(r.memory.id)
    m.created_at = time.time() - 30 * 86400
    svc.backend.put(m)
    assert svc.expire_pending() == 1
    assert svc.get(m.id).status == "expired"


def test_export_import_roundtrip(settings, svc):
    approve(svc, "Prefers tea over coffee.", type="preference", scope="personal")
    data = svc.export_all()
    from memsi.backend.memory_backend import MemoryBackend
    from memsi.core import MemoryService
    from memsi.embed import HashEmbedder

    other = MemoryService(settings, MemoryBackend(None), HashEmbedder())
    assert other.import_all(data) == 1
    assert "tea" in other.recall().text
