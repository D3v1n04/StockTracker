import json
import sys
from email.message import Message

import pytest

from scripts import deployment_smoke


BASE_URL = "https://stocktracker.example"


class FakeResponse:
    def __init__(self, status, content_type="text/plain", body="", location=None):
        self.status = status
        self._body = body.encode("utf-8")
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        if location is not None:
            self.headers["Location"] = location

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback):
        return False


def install_responses(monkeypatch, responses):
    requests = []

    def fake_open(request, _timeout):
        requests.append(request.full_url)
        try:
            response = responses[request.full_url]
        except KeyError as error:
            raise AssertionError(f"Unexpected request to {request.full_url}") from error
        return response

    monkeypatch.setattr(deployment_smoke, "_open_request", fake_open)
    return requests


def success_responses(base_url=BASE_URL):
    return {
        f"{base_url}/": FakeResponse(
            200, "text/html; charset=utf-8", "<title>StockTracker Dashboard</title>"
        ),
        f"{base_url}/health": FakeResponse(
            200, "application/json; charset=utf-8", json.dumps({"status": "ok"})
        ),
        f"{base_url}/ready": FakeResponse(
            200, "application/json", json.dumps({"status": "ready"})
        ),
        f"{base_url}/style.css": FakeResponse(200, "text/css; charset=utf-8", "body {}"),
        f"{base_url}/app.js": FakeResponse(
            200, "application/javascript; charset=utf-8", "const app = true;"
        ),
        f"{base_url}/symbols": FakeResponse(
            200, "application/json", json.dumps({"symbols": []})
        ),
    }


def test_smoke_checks_dashboard_assets_health_ready_and_empty_database_api(monkeypatch):
    requests = install_responses(monkeypatch, success_responses())

    checks = deployment_smoke.run_checks(BASE_URL, "/symbols", 3.0)

    assert len(checks) == 5
    assert checks[-1] == "GET /symbols: valid JSON response"
    assert requests[-1] == f"{BASE_URL}/symbols"


@pytest.mark.parametrize(
    ("location", "target"),
    [
        ("next", f"{BASE_URL}/next"),
        (f"{BASE_URL}/next", f"{BASE_URL}/next"),
    ],
    ids=["relative", "absolute"],
)
def test_same_origin_redirects_are_followed(monkeypatch, location, target):
    requests = install_responses(
        monkeypatch,
        {
            f"{BASE_URL}/symbols": FakeResponse(302, location=location),
            target: FakeResponse(200, "application/json", "{}"),
        },
    )

    assert deployment_smoke._get_json(BASE_URL, "/symbols", 3.0) == {}
    assert requests == [f"{BASE_URL}/symbols", target]


@pytest.mark.parametrize(
    ("location", "reason"),
    [
        ("https://other.example/symbols", "expected origin"),
        ("https://stocktracker.example:444/symbols", "expected origin"),
        ("http://stocktracker.example/symbols", "HTTPS-to-HTTP downgrade"),
        ("//other.example/symbols", "expected origin"),
        ("https://user:password@stocktracker.example/symbols", "must not contain credentials"),
        ("ftp://stocktracker.example/symbols", "must use http or https"),
    ],
    ids=[
        "cross-origin",
        "cross-port",
        "https-downgrade",
        "protocol-relative-external",
        "credentials",
        "unsupported-protocol",
    ],
)
def test_unsafe_redirect_targets_are_rejected(monkeypatch, location, reason):
    install_responses(
        monkeypatch,
        {f"{BASE_URL}/symbols": FakeResponse(302, location=location)},
    )

    with pytest.raises(deployment_smoke.SmokeCheckError, match=reason) as error:
        deployment_smoke._get_json(BASE_URL, "/symbols", 3.0)

    assert f"GET {BASE_URL}/symbols" in str(error.value)


def test_redirect_without_location_is_rejected(monkeypatch):
    install_responses(monkeypatch, {f"{BASE_URL}/symbols": FakeResponse(302)})

    with pytest.raises(deployment_smoke.SmokeCheckError, match="without a Location"):
        deployment_smoke._get_json(BASE_URL, "/symbols", 3.0)


def test_redirect_loop_is_rejected(monkeypatch):
    install_responses(
        monkeypatch,
        {
            f"{BASE_URL}/symbols": FakeResponse(302, location="/other"),
            f"{BASE_URL}/other": FakeResponse(302, location="/symbols"),
        },
    )

    with pytest.raises(deployment_smoke.SmokeCheckError, match="redirect loop"):
        deployment_smoke._get_json(BASE_URL, "/symbols", 3.0)


def test_excessive_redirects_are_rejected(monkeypatch):
    responses = {
        f"{BASE_URL}/symbols": FakeResponse(302, location="/redirect-0"),
    }
    for index in range(deployment_smoke.MAX_REDIRECTS + 1):
        responses[f"{BASE_URL}/redirect-{index}"] = FakeResponse(
            302,
            location=f"/redirect-{index + 1}",
        )
    install_responses(monkeypatch, responses)

    with pytest.raises(deployment_smoke.SmokeCheckError, match="exceeded 5 redirects"):
        deployment_smoke._get_json(BASE_URL, "/symbols", 3.0)


@pytest.mark.parametrize(
    ("css_content_type", "javascript_content_type"),
    [
        ("text/css; charset=utf-8", "application/javascript; charset=utf-8"),
        ("text/css", "text/javascript; charset=utf-8"),
    ],
)
def test_assets_accept_valid_media_types(monkeypatch, css_content_type, javascript_content_type):
    responses = success_responses()
    responses[f"{BASE_URL}/style.css"] = FakeResponse(200, css_content_type, "body {}")
    responses[f"{BASE_URL}/app.js"] = FakeResponse(
        200, javascript_content_type, "const app = true;"
    )
    install_responses(monkeypatch, responses)

    deployment_smoke.run_checks(BASE_URL, "/symbols", 3.0)


@pytest.mark.parametrize(
    ("asset_path", "content_type"),
    [
        ("/style.css", "text/html; charset=utf-8"),
        ("/app.js", "text/html; charset=utf-8"),
        ("/style.css", "application/octet-stream"),
        ("/app.js", "application/json"),
    ],
    ids=["css-html", "javascript-html", "css-generic", "javascript-json"],
)
def test_assets_reject_login_pages_and_incorrect_media_types(
    monkeypatch, asset_path, content_type
):
    responses = success_responses()
    responses[f"{BASE_URL}{asset_path}"] = FakeResponse(
        200, content_type, "<html>Sign in</html>"
    )
    install_responses(monkeypatch, responses)

    with pytest.raises(deployment_smoke.SmokeCheckError, match=asset_path):
        deployment_smoke.run_checks(BASE_URL, "/symbols", 3.0)


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_smoke_check_rejects_non_finite_json(monkeypatch, constant):
    install_responses(
        monkeypatch,
        {f"{BASE_URL}/symbols": FakeResponse(200, "application/json", constant)},
    )

    with pytest.raises(deployment_smoke.SmokeCheckError, match="invalid JSON"):
        deployment_smoke._get_json(BASE_URL, "/symbols", 3.0)


def test_http_localhost_base_url_is_supported(monkeypatch):
    local_base_url = "http://127.0.0.1:8000"
    install_responses(
        monkeypatch,
        {f"{local_base_url}/symbols": FakeResponse(200, "application/json", "{}")},
    )

    assert deployment_smoke._get_json(local_base_url, "/symbols", 3.0) == {}


def test_smoke_script_returns_nonzero_with_clear_failure(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["deployment_smoke.py", "not-a-url"])

    assert deployment_smoke.main() == 1
    assert "SMOKE CHECK FAILED" in capsys.readouterr().err
