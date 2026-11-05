import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def api():
    mod = importlib.import_module("api.index")
    mod.geocode_external.cache_clear()
    return mod


@pytest.fixture(scope="module")
def client(api):
    return TestClient(api.app)


@pytest.fixture(autouse=True)
def no_network(api, monkeypatch):
    monkeypatch.setattr(api, "geocode_external", lambda raw: None)


def test_health_and_meta(client):
    assert client.get("/api/health").json() == {"status": "ok"}
    meta = client.get("/api/meta").json()
    assert meta["dataset"]["label"] == "Fall 2026"
    assert {"today", "alerts", "warnings"} <= set(meta)


def test_stops_include_places(client):
    stops = client.get("/api/stops").json()["stops"]
    assert "University Union" in stops and "Bartle Library" in stops


def test_route_post_depart(client):
    body = {"origin": "University Union", "destination": "University Downtown Center",
            "mode": "depart", "when": "2026-11-04T10:00"}
    r = client.post("/api/route", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["journeys"] and data["origin"]["resolved"] == "University Union"
    assert data["query"]["mode"] == "depart"


def test_route_get_arrive(client):
    r = client.get("/api/route", params={"from": "uu", "to": "UDC", "mode": "arrive", "when": "2026-11-10T09:00"})
    assert r.status_code == 200, r.text
    assert r.json()["journeys"]


def test_bad_inputs(client, api, monkeypatch):
    assert client.post("/api/route", json={"origin": "", "destination": "x"}).status_code == 422
    assert client.post("/api/route", json={"origin": "a", "destination": "b", "access_m": 5000}).status_code == 422
    r = client.post("/api/route", json={"origin": "University Union", "destination": "University Downtown Center",
                                        "mode": "depart", "when": "yesterday"})
    assert r.status_code == 400
    r = client.post("/api/route", json={"origin": "zzzz qqqq", "destination": "University Union"})
    assert r.status_code == 404
    monkeypatch.setattr(api, "geocode_external", lambda raw: (40.7128, -74.0060))
    r = client.post("/api/route", json={"origin": "Times Square", "destination": "University Union"})
    assert r.status_code == 404 and "outside" in r.json()["detail"]
