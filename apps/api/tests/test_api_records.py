from fastapi.testclient import TestClient

from app.repository import InMemoryRepository


def test_dataset_endpoint_declares_the_data_synthetic(client: TestClient) -> None:
    response = client.get("/dataset")

    assert response.status_code == 200
    assert response.json() == {"name": "northstar-cloud", "synthetic": True}


def test_list_services(client: TestClient, repository: InMemoryRepository) -> None:
    response = client.get("/services")

    assert response.status_code == 200
    assert [service["id"] for service in response.json()] == [
        service.id for service in repository.list_services()
    ]


def test_list_tickets(client: TestClient, repository: InMemoryRepository) -> None:
    response = client.get("/tickets")

    assert response.status_code == 200
    assert [ticket["id"] for ticket in response.json()] == [
        ticket.id for ticket in repository.list_tickets()
    ]


def test_ticket_detail_includes_its_incident(client: TestClient) -> None:
    response = client.get("/tickets/TKT-4101")

    assert response.status_code == 200
    assert response.json()["incident_id"] == "INC-1042"


def test_untriaged_ticket_reports_unknown_fields_as_null(client: TestClient) -> None:
    """An untriaged ticket has no service and no priority. The API must say so rather
    than substitute a default that reads as a decision nobody made."""
    response = client.get("/tickets/TKT-4114")

    assert response.status_code == 200
    body = response.json()
    assert body["priority"] is None
    assert body["service_id"] is None
    assert body["incident_id"] is None


def test_unknown_ticket_returns_404(client: TestClient) -> None:
    response = client.get("/tickets/TKT-0000")

    assert response.status_code == 404
    assert "TKT-0000" in response.json()["detail"]


def test_incident_list_carries_ticket_counts(
    client: TestClient, repository: InMemoryRepository
) -> None:
    response = client.get("/incidents")

    assert response.status_code == 200
    counts = repository.count_tickets_by_incident()
    assert {i["id"]: i["ticket_count"] for i in response.json()} == counts


def test_incident_detail_embeds_its_tickets(client: TestClient) -> None:
    response = client.get("/incidents/INC-1043")

    assert response.status_code == 200
    body = response.json()
    assert body["affected_service_ids"] == ["svc-connector", "svc-analytics"]
    assert len(body["tickets"]) == body_ticket_count(client, "INC-1043")


def body_ticket_count(client: TestClient, incident_id: str) -> int:
    listed = client.get("/incidents").json()
    return next(i["ticket_count"] for i in listed if i["id"] == incident_id)


def test_unknown_incident_returns_404(client: TestClient) -> None:
    response = client.get("/incidents/INC-0000")

    assert response.status_code == 404
    assert "INC-0000" in response.json()["detail"]
