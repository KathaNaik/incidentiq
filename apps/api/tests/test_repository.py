from app.repository import InMemoryRepository


def test_tickets_are_ordered_newest_first(repository: InMemoryRepository) -> None:
    created = [ticket.created_at for ticket in repository.list_tickets()]

    assert created == sorted(created, reverse=True)


def test_incidents_are_ordered_by_detection_time(repository: InMemoryRepository) -> None:
    detected = [incident.detected_at for incident in repository.list_incidents()]

    assert detected == sorted(detected, reverse=True)


def test_unknown_ids_return_none(repository: InMemoryRepository) -> None:
    assert repository.get_ticket("TKT-0000") is None
    assert repository.get_incident("INC-0000") is None


def test_incident_tickets_resolve_both_directions(
    repository: InMemoryRepository,
) -> None:
    tickets = repository.list_tickets_for_incident("INC-1042")

    assert tickets, "expected the declared cluster to resolve to tickets"
    for ticket in tickets:
        assert repository.get_incident_id_for_ticket(ticket.id) == "INC-1042"


def test_counts_match_the_resolved_ticket_lists(repository: InMemoryRepository) -> None:
    counts = repository.count_tickets_by_incident()

    assert set(counts) == {incident.id for incident in repository.list_incidents()}
    for incident_id, count in counts.items():
        assert count == len(repository.list_tickets_for_incident(incident_id))


def test_unlinked_tickets_belong_to_no_incident(repository: InMemoryRepository) -> None:
    linked = {
        ticket.id
        for incident in repository.list_incidents()
        for ticket in repository.list_tickets_for_incident(incident.id)
    }
    unlinked = [t for t in repository.list_tickets() if t.id not in linked]

    assert unlinked, "fixtures should include standalone tickets"
    for ticket in unlinked:
        assert repository.get_incident_id_for_ticket(ticket.id) is None
