import pytest

from memsi.backend.memory_backend import MemoryBackend
from memsi.config import AutoApproveRule, ReadFilter, Settings
from memsi.core import MemoryService
from memsi.embed import HashEmbedder


@pytest.fixture
def settings():
    return Settings(
        owner="test",
        backend="memory",
        embedder="hash",
        auto_approve=[AutoApproveRule(type="project", min_confidence=0.85, sources=["claude-code"], require_no_neighbours=True)],
        read_filters={"chatgpt": ReadFilter(sensitivity_max="internal")},
    )


@pytest.fixture
def svc(settings):
    return MemoryService(settings, MemoryBackend(None), HashEmbedder())


def approve(svc, content, **kw):
    r = svc.propose(content, source_app="test", **kw)
    assert r.status == "pending", r.status
    return svc.confirm(r.memory.id, "approve", user_quote="yes", via="test")
