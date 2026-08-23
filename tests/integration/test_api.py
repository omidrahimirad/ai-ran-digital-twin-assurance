from datetime import UTC, datetime

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


def test_metrics_use_bounded_route_labels(client: TestClient) -> None:
    assert client.get("/arbitrary/untrusted/path-12345").status_code == 404
    metrics = client.get("/metrics").text
    assert 'path="unmatched"' in metrics
    assert "path-12345" not in metrics


def test_run_scenario_and_invalid_requests(client: TestClient) -> None:
    response = client.post("/scenarios/run", json={"scenario": "outage"})
    assert response.status_code == 200
    assert response.json()["scenario"] == "outage"
    assert response.json()["synthetic_data"] is True
    assert client.post("/scenarios/run", json={"scenario": "bad"}).status_code == 422
    assert (
        client.post("/scenarios/run", json={"scenario": "outage", "steps": 10}).status_code == 422
    )
    assert (
        client.post("/scenarios/run", json={"scenario": "outage", "unexpected": True}).status_code
        == 422
    )
    assert client.post("/scenarios/run", json={"scenario": "Outage!"}).status_code == 422


def test_action_validation_endpoint(client: TestClient) -> None:
    client.post("/scenarios/run", json={"scenario": "congestion"})
    decision = next(
        item
        for item in client.get("/decisions").json()
        if item["action"]["action_type"] == "activate_additional_capacity"
    )
    timestamp = decision["action"]["proposed_at"]
    response = client.post(
        "/actions/validate",
        json={
            "action": decision["action"],
            "telemetry_timestamp": timestamp,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["shadow_mode"] is True
    assert body["prediction"] == decision["prediction"]
    assert body["result"]["approved"] is False
    assert "telemetry is stale" in body["result"]["violations"]


def test_action_validation_rejects_client_prediction_time_and_unstored_data(
    client: TestClient,
) -> None:
    client.post("/scenarios/run", json={"scenario": "congestion"})
    decision = next(
        item
        for item in client.get("/decisions").json()
        if item["action"]["action_type"] == "activate_additional_capacity"
    )
    action = decision["action"]
    timestamp = action["proposed_at"]
    injected = client.post(
        "/actions/validate",
        json={
            "action": action,
            "telemetry_timestamp": timestamp,
            "prediction": decision["prediction"],
            "evaluated_at": timestamp,
        },
    )
    assert injected.status_code == 422
    assert {item["loc"][-1] for item in injected.json()["detail"]} == {
        "prediction",
        "evaluated_at",
    }

    forged = client.post(
        "/actions/validate",
        json={
            "action": action,
            "telemetry_timestamp": datetime.now(UTC).isoformat(),
        },
    )
    assert forged.status_code == 422
    assert "stored synthetic telemetry" in forged.json()["detail"]

    naive = client.post(
        "/actions/validate",
        json={"action": action, "telemetry_timestamp": "2026-01-01T00:00:00"},
    )
    assert naive.status_code == 422


def test_action_validation_rejects_invalid_action_parameters(client: TestClient) -> None:
    client.post("/scenarios/run", json={"scenario": "congestion"})
    decision = next(
        item
        for item in client.get("/decisions").json()
        if item["action"]["action_type"] == "activate_additional_capacity"
    )
    action = decision["action"]
    action["parameters"] = {"capacity_delta_pct": 15, "shell_command": "unsafe"}
    response = client.post(
        "/actions/validate",
        json={"action": action, "telemetry_timestamp": action["proposed_at"]},
    )
    assert response.status_code == 422
    assert "parameters must be exactly" in str(response.json())


def test_fixture_investigation_is_server_side_advisory_and_observable(
    client: TestClient,
) -> None:
    client.post("/scenarios/run", json={"scenario": "congestion"})
    response = client.post("/investigations", json={"provider": "fixture"})
    assert response.status_code == 200
    body = response.json()
    assert body["investigation"]["provider"]["live_model"] is False
    assert body["investigation"]["output"]["primary_hypothesis"] == "congestion"
    assert body["verification"]["status"] == "verified"
    assert body["advisory_only"] is True
    assert body["can_modify_shadow_decision"] is False
    serialized_context = str(body["context"])
    for forbidden in ("ground_truth", "target_cells", "fault_type", "severity"):
        assert forbidden not in serialized_context
    metrics = client.get("/metrics").text
    assert "ai_ran_investigations_total" in metrics


def test_investigation_request_rejects_truth_output_and_unavailable_live_provider(
    client: TestClient, monkeypatch: object
) -> None:
    injected = client.post(
        "/investigations",
        json={
            "provider": "fixture",
            "ground_truth": "congestion",
            "model_output": {"primary_hypothesis": "congestion"},
            "verification": {"status": "verified"},
            "command": "apply change",
        },
    )
    assert injected.status_code == 422
    fields = {item["loc"][-1] for item in injected.json()["detail"]}
    assert fields == {"ground_truth", "model_output", "verification", "command"}
    unavailable = client.post("/investigations", json={"provider": "openai"})
    assert unavailable.status_code == 503
    assert "live provider disabled" in unavailable.json()["detail"]
    assert (
        client.post(
            "/investigations", json={"provider": "fixture", "cell_id": "not-a-cell"}
        ).status_code
        == 422
    )
