import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.llm.errors import ProviderUnavailableError
from backend.core.llm.routes import router, router_dep
from backend.tests.test_llm_router import make

SECRET = "AIzaSECRETSECRETSECRETSECRETSECRETSECRET1"


@pytest.fixture
def client():
    r, gem, oll, _ = make(["cloud-answer"], ["local-answer"])
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[router_dep] = lambda: r
    return TestClient(app), r, gem, oll


def test_status_has_no_secrets_and_shows_configuration(client):
    c, r, gem, oll = client
    body = c.get("/llm/status", params={"live": "false"}).json()
    assert body["selection"] == "auto" and body["providers"]["gemini"]["configured"] is True
    assert "api_key" not in str(body).lower() and SECRET not in str(body)


def test_selection_roundtrip_and_validation(client):
    c, r, *_ = client
    assert c.put("/llm/selection", json={"provider": "ollama"}).json()["selection"] == "ollama"
    assert c.put("/llm/selection", json={"provider": "openai"}).status_code == 400
    assert c.put("/llm/selection", json={"provider": "BAD NAME!"}).status_code == 422


def test_task_route_validation(client):
    c, *_ = client
    ok = c.put("/llm/tasks/plan", json={"targets": [{"provider": "gemini", "model": "gemini-3.5-flash"}]})
    assert ok.status_code == 200
    assert c.put("/llm/tasks/plan", json={"targets": [{"provider": "gemini", "model": "a b?x=1"}]}).status_code == 422
    assert c.put("/llm/tasks/plan", json={"targets": []}).status_code == 422
    assert c.put("/llm/tasks/Bad-Task", json={"targets": [{"provider": "gemini"}]}).status_code == 422


def test_test_endpoint_reports_fallback_and_usage(client):
    c, r, gem, oll = client
    gem.script = [ProviderUnavailableError("down", "gemini", retryable=False)]
    body = c.post("/llm/test", json={"prompt": "hi"}).json()
    assert body["provider"] == "ollama" and body["fell_back"] is True
    usage = c.get("/llm/usage", params={"recent": 5}).json()
    assert {x["provider"] for x in usage["today"]} == {"gemini", "ollama"}
    assert usage["recent"][0]["provider"] == "ollama"


def test_test_endpoint_503_when_nothing_available(client):
    c, r, gem, oll = client
    gem.script = [ProviderUnavailableError("down", "gemini", retryable=False)]
    oll.script = [ProviderUnavailableError("Ollama is not reachable", "ollama", retryable=False)]
    resp = c.post("/llm/test", json={"prompt": "hi"})
    assert resp.status_code == 503 and resp.json()["detail"]["attempts"][1]["provider"] == "ollama"
