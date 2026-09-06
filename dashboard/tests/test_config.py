from dashboard.config import Config


def test_default_host_is_loopback_not_all_interfaces(monkeypatch):
    # Regression: 0.0.0.0 with no auth and no rate limiting is a data-leak
    # and DoS vector if the deployment's port-forward-only assumption ever
    # slips. kubectl port-forward reaches a pod's own network namespace
    # directly, so loopback is a safe default that doesn't break it.
    monkeypatch.delenv("DASHBOARD_HOST", raising=False)
    config = Config.from_env()
    assert config.server_host == "127.0.0.1"


def test_auth_token_defaults_to_none(monkeypatch):
    monkeypatch.delenv("DASHBOARD_AUTH_TOKEN", raising=False)
    config = Config.from_env()
    assert config.auth_token is None


def test_auth_token_empty_string_treated_as_unset(monkeypatch):
    monkeypatch.setenv("DASHBOARD_AUTH_TOKEN", "")
    config = Config.from_env()
    assert config.auth_token is None


def test_rate_limit_defaults(monkeypatch):
    monkeypatch.delenv("DASHBOARD_RATE_LIMIT_MAX_REQUESTS", raising=False)
    monkeypatch.delenv("DASHBOARD_RATE_LIMIT_WINDOW_SECONDS", raising=False)
    config = Config.from_env()
    assert config.rate_limit_max_requests == 60
    assert config.rate_limit_window_seconds == 60.0
