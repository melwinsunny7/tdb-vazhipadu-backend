import app.main as main_module
import app.offerings as offerings_module
import app.orders as orders_module
import pytest
from app.database import get_connection, initialize_database
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def temple_api(tmp_path, monkeypatch):
	database_path = tmp_path / "temple-orders.db"
	monkeypatch.setattr(
		main_module,
		"initialize_database",
		lambda: initialize_database(database_path),
	)
	monkeypatch.setattr(
		offerings_module,
		"get_connection",
		lambda: get_connection(database_path),
	)
	monkeypatch.setattr(
		orders_module,
		"get_connection",
		lambda: get_connection(database_path),
	)
	with TestClient(app) as client:
		yield client, database_path


def _create_temple(client, name: str) -> int:
	response = client.post("/temples", json={"name": name})
	assert response.status_code == 201
	return response.json()["id"]


def _create_offering(client, name: str = "Archana", price: str = "42.50") -> int:
	response = client.post(
		"/offerings", json={"name": name, "price": price, "active": True}
	)
	assert response.status_code == 201
	return response.json()["id"]


def _map_offering(client, temple_id: int, offering_id: int, active: bool = True):
	return client.post(
		f"/temples/{temple_id}/offerings",
		json={"offering_id": offering_id, "active": active},
	)


def _order_payload(temple_id: int | None, offering_id: int) -> dict:
	payload = {
		"devotee_name": "Lakshmi Devi",
		"phone_number": "9876543210",
		"birth_star": "Rohini",
		"booking_date": "2026-10-26",
		"items": [{"offering_id": offering_id, "quantity": 2}],
	}
	if temple_id is not None:
		payload["temple_id"] = temple_id
	return payload


def test_order_without_temple_is_rejected(temple_api):
	client, _ = temple_api
	temple_id = _create_temple(client, "First Temple")
	offering_id = _create_offering(client)
	assert _map_offering(client, temple_id, offering_id).status_code == 201

	response = client.post("/orders", json=_order_payload(None, offering_id))

	assert response.status_code == 422
	assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_unmapped_offering_cannot_be_booked_at_temple(temple_api):
	client, _ = temple_api
	selected_temple = _create_temple(client, "Selected Temple")
	other_temple = _create_temple(client, "Other Temple")
	offering_id = _create_offering(client)
	assert _map_offering(client, other_temple, offering_id).status_code == 201

	response = client.post(
		"/orders", json=_order_payload(selected_temple, offering_id)
	)

	assert response.status_code == 422
	assert response.json()["error"]["code"] == "OFFERING_NOT_MAPPED"


def test_inactive_temple_mapping_cannot_be_booked(temple_api):
	client, _ = temple_api
	temple_id = _create_temple(client, "Inactive Mapping Temple")
	offering_id = _create_offering(client)
	assert _map_offering(client, temple_id, offering_id, active=False).status_code == 201

	response = client.post("/orders", json=_order_payload(temple_id, offering_id))

	assert response.status_code == 422
	assert response.json()["error"]["code"] == "INACTIVE_OFFERING"


def test_valid_temple_booking_uses_one_shared_offering_price(temple_api):
	client, database_path = temple_api
	first_temple = _create_temple(client, "Temple One")
	second_temple = _create_temple(client, "Temple Two")
	offering_id = _create_offering(client, price="42.50")
	assert _map_offering(client, first_temple, offering_id).status_code == 201
	assert _map_offering(client, second_temple, offering_id).status_code == 201

	response = client.post(
		"/orders", json=_order_payload(first_temple, offering_id)
	)

	assert response.status_code == 201
	order = response.json()
	assert order["temple_id"] == first_temple
	assert order["items"][0]["unit_price"] == "42.5"
	assert order["total"] == "85"
	connection = get_connection(database_path)
	try:
		assert connection.execute("SELECT COUNT(*) FROM offerings").fetchone()[0] == 1
		assert connection.execute(
			"SELECT price_paise FROM offerings WHERE offering_id = ?", (offering_id,)
		).fetchone()[0] == 4250
		assert connection.execute(
			"SELECT unit_price_paise FROM order_items WHERE order_id = ?",
			(order["id"],),
		).fetchone()[0] == 4250
	finally:
		connection.close()


def test_temple_offering_limit_can_be_set_and_cleared(temple_api):
	client, _ = temple_api
	temple_id = _create_temple(client, "Limit Temple")
	offering_id = _create_offering(client)
	mapping = _map_offering(client, temple_id, offering_id)
	assert mapping.status_code == 201

	updated = client.patch(
		f"/temples/{temple_id}/offerings/{offering_id}",
		json={"daily_limit": 12},
	)
	cleared = client.patch(
		f"/temples/{temple_id}/offerings/{offering_id}",
		json={"daily_limit": None},
	)

	assert updated.status_code == 200
	assert updated.json()["daily_limit"] == 12
	assert cleared.status_code == 200
	assert cleared.json()["daily_limit"] is None


def test_omitted_daily_limit_allows_multiple_orders(temple_api):
	client, _ = temple_api
	temple_id = _create_temple(client, "Unlimited Temple")
	offering_id = _create_offering(client)
	assert _map_offering(client, temple_id, offering_id).status_code == 201

	first_order = client.post(
		"/orders", json=_order_payload(temple_id, offering_id)
	)
	second_order = client.post(
		"/orders", json=_order_payload(temple_id, offering_id)
	)
	mappings = client.get(f"/temples/{temple_id}/offerings")

	assert first_order.status_code == 201
	assert second_order.status_code == 201
	assert mappings.status_code == 200
	assert mappings.json()[0]["daily_limit"] is None


def test_list_temples_returns_all_temples_in_creation_order(temple_api):
	client, _ = temple_api
	first_temple_id = _create_temple(client, "First Temple")
	second_temple_id = _create_temple(client, "Second Temple")

	response = client.get("/temples")

	assert response.status_code == 200
	assert response.json() == [
		{"id": first_temple_id, "name": "First Temple"},
		{"id": second_temple_id, "name": "Second Temple"},
	]


def test_list_temple_offerings_returns_limits_shared_prices_and_status(temple_api):
	client, _ = temple_api
	temple_id = _create_temple(client, "Mapping List Temple")
	first_offering_id = _create_offering(client, "Archana", "42.50")
	second_offering_id = _create_offering(client, "Pushpanjali", "30.00")
	assert _map_offering(client, temple_id, first_offering_id).status_code == 201
	assert client.post(
		f"/temples/{temple_id}/offerings",
		json={
			"offering_id": second_offering_id,
			"active": False,
			"daily_limit": 8,
		},
	).status_code == 201

	response = client.get(f"/temples/{temple_id}/offerings")

	assert response.status_code == 200
	assert response.json() == [
		{
			"temple_id": temple_id,
			"offering_id": first_offering_id,
			"name": "Archana",
			"price": "42.5",
			"active": True,
			"daily_limit": None,
		},
		{
			"temple_id": temple_id,
			"offering_id": second_offering_id,
			"name": "Pushpanjali",
			"price": "30",
			"active": False,
			"daily_limit": 8,
		},
	]


def test_list_temple_offerings_returns_not_found_for_unknown_temple(temple_api):
	client, _ = temple_api

	response = client.get("/temples/999/offerings")

	assert response.status_code == 404
	assert response.json()["error"]["code"] == "TEMPLE_NOT_FOUND"