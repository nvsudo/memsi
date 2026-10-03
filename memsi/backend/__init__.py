from .base import Backend, Filters

__all__ = ["Backend", "Filters", "make_backend"]


def make_backend(settings):
    if settings.backend == "redis":
        from .redis_backend import RedisBackend

        return RedisBackend(settings.redis_url, settings.owner)
    if settings.backend == "memory":
        from .memory_backend import MemoryBackend

        return MemoryBackend(settings.data_dir / "dev.json")
    raise ValueError(f"unknown backend: {settings.backend}")
