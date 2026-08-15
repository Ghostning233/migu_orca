from __future__ import annotations

from mikan_engine.controllers.mikan_candidate_cache import (
    CandidateSearchCache,
    candidate_cache_key,
)
from mikan_engine.controllers.mikan_client import MikanCandidate
from mikan_engine.controllers.mikan_config import MikanConfig


def _config(endpoint: str = "https://mikan.example/Home/Search") -> MikanConfig:
    return MikanConfig(search_endpoint=endpoint, timeout_seconds=5)


def _candidate(
    bangumi_id: str = "2353",
    title: str = "葬送的芙莉莲",
    *,
    source_query: str = "芙莉莲",
    aliases: list[str] | None = None,
) -> MikanCandidate:
    return MikanCandidate(
        bangumi_id=bangumi_id,
        title=title,
        mikan_url=f"https://mikan.example/Home/Bangumi/{bangumi_id}",
        source_query=source_query,
        aliases=list(aliases or []),
    )


def _fake_clock(start: float = 1000.0) -> tuple[dict[str, float], "object"]:
    holder = {"value": start}

    def _now() -> float:
        return holder["value"]

    return holder, _now


def test_candidate_cache_key_normalizes_query_whitespace() -> None:
    assert candidate_cache_key("  芙莉莲  ", _config()) == candidate_cache_key(
        "芙莉莲", _config()
    )
    assert candidate_cache_key("芙莉莲  S2", _config()) == candidate_cache_key(
        " 芙莉莲 S2 ", _config()
    )


def test_candidate_cache_key_isolates_different_queries() -> None:
    assert candidate_cache_key("芙莉莲", _config()) != candidate_cache_key(
        "咒术回战", _config()
    )


def test_candidate_cache_key_isolates_different_hosts() -> None:
    key_mikan = candidate_cache_key(
        "芙莉莲", _config("https://mikan.example/Home/Search")
    )
    key_other = candidate_cache_key(
        "芙莉莲", _config("https://other.example/Home/Search")
    )
    assert key_mikan != key_other


def test_candidate_cache_key_isolates_different_config_identities() -> None:
    # Different paths/query on the same host still change the identity digest.
    assert candidate_cache_key(
        "芙莉莲", _config("https://mikan.example/Home/Search")
    ) != candidate_cache_key(
        "芙莉莲", _config("https://mikan.example/Home/Search?classic=true")
    )


def test_candidate_cache_key_never_contains_sensitive_values() -> None:
    config = _config("https://mikan.example/Home/Search?token=secret&cookie=session")
    key = candidate_cache_key("芙莉莲", config)

    assert key.startswith("mikan-candidates:")
    assert "secret" not in key
    assert "cookie" not in key
    assert "session" not in key
    assert "mikan.example" not in key
    assert "Home/Search" not in key


def test_candidate_cache_miss_returns_none() -> None:
    cache = CandidateSearchCache()

    assert cache.get("missing-key") is None
    assert len(cache) == 0


def test_candidate_cache_set_then_get_roundtrips() -> None:
    cache = CandidateSearchCache()
    candidates = [_candidate(), _candidate("3072", "咒术回战 第三季")]

    cache.set("key-1", candidates)

    assert cache.get("key-1") == candidates
    assert len(cache) == 1


def test_candidate_cache_get_returns_immutable_copies() -> None:
    cache = CandidateSearchCache()
    cache.set("key-1", [_candidate(aliases=["Frieren EN"])])

    first = cache.get("key-1")
    assert first is not None
    first[0].aliases.append("mutated")
    first.append(_candidate("9999", "被篡改"))

    second = cache.get("key-1")
    assert second is not None
    assert second[0].aliases == ["Frieren EN"]
    assert len(second) == 1


def test_candidate_cache_ttl_expires_entries() -> None:
    holder, now = _fake_clock(1000.0)
    cache = CandidateSearchCache(ttl_seconds=300, now=now)  # type: ignore[arg-type]
    cache.set("key-1", [_candidate()])

    holder["value"] += 299.9
    assert cache.get("key-1") is not None

    holder["value"] += 0.2  # past the 300s TTL
    assert cache.get("key-1") is None
    assert len(cache) == 0


def test_candidate_cache_clear_removes_all_entries() -> None:
    cache = CandidateSearchCache()
    cache.set("key-1", [_candidate("1")])
    cache.set("key-2", [_candidate("2")])
    assert len(cache) == 2

    cache.clear()

    assert len(cache) == 0
    assert cache.get("key-1") is None
    assert cache.get("key-2") is None


def test_candidate_cache_is_bounded_to_max_entries() -> None:
    holder, now = _fake_clock(0.0)
    cache = CandidateSearchCache(max_entries=2, now=now)  # type: ignore[arg-type]
    for index in range(3):
        cache.set(f"key-{index}", [_candidate(str(index), f"番剧 {index}")])

    assert len(cache) == 2
    # The oldest entry (key-0) was evicted.
    assert cache.get("key-0") is None
    assert cache.get("key-1") is not None
    assert cache.get("key-2") is not None


def test_candidate_cache_refresh_does_not_evict_existing_entry() -> None:
    holder, now = _fake_clock(0.0)
    cache = CandidateSearchCache(max_entries=2, now=now)  # type: ignore[arg-type]
    cache.set("key-1", [_candidate("1")])
    cache.set("key-2", [_candidate("2")])

    # Refreshing an existing key must not count toward the bound.
    cache.set("key-1", [_candidate("1", "更新后的番剧")])
    assert len(cache) == 2
    assert cache.get("key-1")[0].title == "更新后的番剧"
    assert cache.get("key-2") is not None


def test_candidate_cache_snapshot_contains_only_safe_fields() -> None:
    cache = CandidateSearchCache()
    cache.set(
        "mikan-candidates:deadbeef:芙莉莲",
        [_candidate(aliases=["Frieren EN"])],
    )

    snapshot = cache.snapshot()

    assert len(snapshot) == 1
    entry = snapshot[0]
    assert set(entry.keys()) == {"key", "query", "timestamp", "candidates"}
    assert entry["query"] == "芙莉莲"
    candidate = entry["candidates"][0]
    assert set(candidate.keys()) == {
        "bangumi_id",
        "title",
        "mikan_url",
        "poster_url",
        "source_query",
        "aliases",
    }
    assert candidate["aliases"] == ["Frieren EN"]

    serialized = repr(snapshot)
    for forbidden in ("token", "cookie", "<html", "<rss", "raw_html", "raw_rss"):
        assert forbidden not in serialized
