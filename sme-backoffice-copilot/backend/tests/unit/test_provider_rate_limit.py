from ssl import CERT_REQUIRED

import pytest

from app.providers.rate_limit import RedisFixedWindowProviderRateLimiter


@pytest.mark.parametrize(
    ("redis_url", "expects_tls"),
    [
        ("redis://localhost:6379/2", False),
        ("rediss://:token@upstash.example:6379/2?ssl_cert_reqs=CERT_REQUIRED", True),
    ],
)
def test_rate_limiter_only_passes_tls_options_for_rediss_urls(
    monkeypatch: pytest.MonkeyPatch,
    redis_url: str,
    expects_tls: bool,
) -> None:
    captured: dict[str, object] = {}

    def fake_from_url(url: str, **options: object) -> object:
        captured["url"] = url
        captured["options"] = options
        return object()

    monkeypatch.setattr(
        "app.providers.rate_limit.Redis.from_url",
        fake_from_url,
    )

    RedisFixedWindowProviderRateLimiter.from_url(
        redis_url=redis_url,
        ocr_requests_per_second=1,
        llm_requests_per_second=1,
        wait_timeout_seconds=1,
    )

    options = captured["options"]
    assert isinstance(options, dict)
    assert options["decode_responses"] is True
    assert ("ssl_cert_reqs" in options) is expects_tls
    if expects_tls:
        assert options["ssl_cert_reqs"] == CERT_REQUIRED
    assert "ssl_cert_reqs" not in str(captured["url"])
