"""
The OpenAPI spec is generated from api.server.routes, not maintained by hand a
second time. These tests are what makes that guarantee real: a route added to
server.py and never reflected in the spec fails here, rather than the docs
quietly drifting out of date — which is how every hand-maintained API doc dies.
"""
import os
os.environ.setdefault("ARTHA_SECRET_KEY", "test-secret-key-not-for-production-use-only")

from starlette.routing import Route
from starlette.testclient import TestClient

from api import openapi
from api.server import app, routes, PUBLIC_PATHS


def _all_http_operations():
    """{(method, path)} for every Route in the live table — WebSocketRoute (/ws)
    is excluded, it has no HTTP methods to enumerate."""
    out = set()
    for r in routes:
        if not isinstance(r, Route):
            continue
        for m in (r.methods or {"GET"}):
            if m != "HEAD":
                out.add((m, r.path))
    return out


def test_every_registered_route_appears_in_the_spec():
    spec = openapi.build_spec(routes)
    documented = {
        (method.upper(), path)
        for path, methods in spec["paths"].items()
        for method in methods
    }
    missing = _all_http_operations() - documented
    assert not missing, f"routes registered but absent from the OpenAPI spec: {missing}"


def test_the_spec_documents_no_route_that_does_not_exist():
    """The inverse check — a stale entry describing a route since removed
    would mislead a reader just as badly as a missing one."""
    spec = openapi.build_spec(routes)
    documented = {
        (method.upper(), path)
        for path, methods in spec["paths"].items()
        for method in methods
        if path != "/ws"  # hand-spliced, not enumerated from `routes`
    }
    extra = documented - _all_http_operations()
    assert not extra, f"spec documents routes that are not registered: {extra}"


def test_security_matches_public_paths_exactly():
    """openapi.py keeps its own _PUBLIC_PATHS so build_spec has no import-time
    dependency on server.py. This is what keeps the two from silently diverging
    — a route made public in one and not the other is a real security question,
    not a docs nit."""
    assert openapi._PUBLIC_PATHS == PUBLIC_PATHS


def test_public_routes_carry_no_401_and_an_empty_security_override():
    spec = openapi.build_spec(routes)
    for path in PUBLIC_PATHS:
        if path == "/api/docs":
            continue  # HTML response, not JSON — no operation-level 401 shape to check
        for op in spec["paths"].get(path, {}).values():
            assert op.get("security") == [], f"{path} should override security to []"
            assert "401" not in op["responses"], f"{path} is public but documents a 401"


def test_protected_routes_all_document_a_401():
    spec = openapi.build_spec(routes)
    for path, methods in spec["paths"].items():
        if path in PUBLIC_PATHS or path == "/ws":
            continue
        for method, op in methods.items():
            assert "401" in op["responses"], f"{method.upper()} {path} is protected but has no documented 401"
            assert "security" not in op, f"{method.upper()} {path} should inherit the global bearer requirement"


def test_the_bearer_scheme_is_declared():
    spec = openapi.build_spec(routes)
    scheme = spec["components"]["securitySchemes"]["bearerAuth"]
    assert scheme["type"] == "http"
    assert scheme["scheme"] == "bearer"


def test_path_parameters_are_reflected():
    spec = openapi.build_spec(routes)
    op = spec["paths"]["/api/fno/{index}"]["get"]
    names = {p["name"] for p in op["parameters"]}
    assert "index" in names


def test_the_endpoint_serves_valid_json_matching_the_generator():
    client = TestClient(app)
    r = client.get("/api/openapi.json")
    assert r.status_code == 200
    body = r.json()
    assert body["openapi"] == "3.1.0"
    assert body["paths"] == openapi.build_spec(routes)["paths"]


def test_the_openapi_endpoint_itself_needs_no_token():
    client = TestClient(app)
    assert client.get("/api/openapi.json").status_code == 200


def test_swagger_ui_serves_without_a_token():
    client = TestClient(app)
    r = client.get("/api/docs")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_swagger_ui_references_no_external_cdn():
    """The whole reason for vendoring: a self-hosted terminal's own API docs
    should not require internet access, and a third-party <script> tag on a
    page that exercises bearer tokens is an avoidable supply-chain surface."""
    html = openapi.swagger_ui_html("/api/openapi.json")
    for banned in ("cdn.", "unpkg.com", "jsdelivr", "googleapis.com/css"):
        assert banned not in html, f"Swagger UI page references an external host: {banned}"
