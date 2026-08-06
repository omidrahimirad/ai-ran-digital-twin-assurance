from fastapi.testclient import TestClient


def test_read_endpoints_and_default_run(client: TestClient) -> None:
    assert client.get("/health").json() == {
        "status": "ok",
        "mode": "shadow",
        "synthetic_data": True,
    }
    assert len(client.get("/cells").json()) == 20
    assert len(client.get("/network").json()["neighbor_relations"]) == 80
    assert client.get("/telemetry").status_code == 200
    assert client.get("/anomalies").json()
    assert client.get("/diagnoses").json()
    assert client.get("/recommendations").json()
    assert client.get("/decisions").json()
    assert "ai_ran_api_requests_total" in client.get("/metrics").text


def test_run_scenario_and_invalid_requests(client: TestClient) -> None:
    response = client.post("/scenarios/run", json={"scenario": "outage"})
    assert response.status_code == 200
    assert response.json()["scenario"] == "outage"
    assert response.json()["synthetic_data"] is True
    assert client.post("/scenarios/run", json={"scenario": "bad"}).status_code == 422
    assert (
        client.post("/scenarios/run", json={"scenario": "outage", "steps": 10}).status_code == 422
    )


def test_action_validation_endpoint(client: TestClient) -> None:
    client.post("/scenarios/run", json={"scenario": "congestion"})
    decision = client.get("/decisions").json()[0]
    timestamp = decision["action"]["proposed_at"]
    response = client.post(
        "/actions/validate",
        json={
            "action": decision["action"],
            "prediction": decision["prediction"],
            "telemetry_timestamp": timestamp,
            "evaluated_at": timestamp,
        },
    )
    assert response.status_code == 200
    assert response.json() == {
        "result": response.json()["result"],
        "shadow_mode": True,
    }
    stale = response.json()["result"]["evaluated_at"]
    assert stale
