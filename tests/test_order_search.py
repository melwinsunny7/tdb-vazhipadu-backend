import sqlite3

import app.main as main_module
import app.offerings as offerings_module
import app.orders as orders_module
import pytest
from app.database import get_connection, initialize_database
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def search_context(tmp_path, monkeypatch):
	database_path = tmp_path / "data" / "orders.db"
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
		offering_response = client.post(
			"/offerings",
			json={"name": "Pushpanjali", "price": "30.00", "active": True},
		)
		assert offering_response.status_code == 201
		offering_id = offering_response.json()["id"]

		order_data = [
			("Mira", "9876543210", "2026-10-20", "BOOKED"),
			("Ravi", "9123456780", "2026-10-21", "CANCELLED"),
			("Mira", "9876543210", "2026-10-21", "BOOKED"),
			("Leela", "9987654321", "2026-10-20", "COMPLETED"),
			("Ravi", "9123456780", "2026-10-20", "BOOKED"),
			("Hari", "9001234567", "2026-10-22", "CANCELLED"),
		]
		order_ids = []
		for name, phone, booking_date, _ in order_data:
			response = client.post(
				"/orders",
				json={
					"devotee_name": name,
					"phone_number": phone,
					"birth_star": "Ashwini",
					"booking_date": booking_date,
					"items": [{"offering_id": offering_id, "quantity": 1}],
				},
			)
			assert response.status_code == 201
			order_ids.append(response.json()["id"])

		connection = get_connection(database_path)
		try:
			with connection:
				for order_id, (_, _, _, order_status) in zip(order_ids, order_data):
					connection.execute(
						"UPDATE orders SET status = ? WHERE order_id = ?",
						(order_status, order_id),
					)
		finally:
			connection.close()

		yield client, database_path, order_ids


def test_phone_search_returns_only_exact_matches(search_context):
	client, _, order_ids = search_context

	response = client.get("/orders", params={"phone_number": "9876543210"})

	assert response.status_code == 200
	assert [order["id"] for order in response.json()["orders"]] == [
		order_ids[2],
		order_ids[0],
	]


def test_booking_date_filter(search_context):
	client, _, order_ids = search_context

	response = client.get("/orders", params={"booking_date": "2026-10-20"})

	assert response.status_code == 200
	assert [order["id"] for order in response.json()["orders"]] == [
		order_ids[4],
		order_ids[3],
		order_ids[0],
	]


def test_status_filter(search_context):
	client, _, order_ids = search_context

	response = client.get("/orders", params={"status": "CANCELLED"})

	assert response.status_code == 200
	assert [order["id"] for order in response.json()["orders"]] == [
		order_ids[5],
		order_ids[1],
	]


def test_combined_filters_return_intersection(search_context):
	client, _, order_ids = search_context

	response = client.get(
		"/orders",
		params={
			"booking_date": "2026-10-20",
			"status": "BOOKED",
			"phone_number": "9123456780",
		},
	)

	assert response.status_code == 200
	assert [order["id"] for order in response.json()["orders"]] == [order_ids[4]]


def test_pagination_has_expected_page_size_and_metadata(search_context):
	client, _, order_ids = search_context

	response = client.get("/orders", params={"page": 2, "page_size": 2})

	assert response.status_code == 200
	assert response.json()["page"] == 2
	assert response.json()["page_size"] == 2
	assert response.json()["total"] == 6
	assert response.json()["total_pages"] == 3
	assert [order["id"] for order in response.json()["orders"]] == [
		order_ids[3],
		order_ids[2],
	]


def test_consecutive_pages_do_not_overlap(search_context):
	client, _, order_ids = search_context

	first_page = client.get("/orders", params={"page": 1, "page_size": 2})
	second_page = client.get("/orders", params={"page": 2, "page_size": 2})
	first_ids = [order["id"] for order in first_page.json()["orders"]]
	second_ids = [order["id"] for order in second_page.json()["orders"]]

	assert first_ids == [order_ids[5], order_ids[4]]
	assert second_ids == [order_ids[3], order_ids[2]]
	assert set(first_ids).isdisjoint(second_ids)


def test_invalid_query_parameters_use_standard_error_format(search_context):
	client, _, _ = search_context

	for params in (
		{"page": 0},
		{"page_size": 101},
		{"booking_date": "not-a-date"},
		{"phone_number": "invalid"},
	):
		response = client.get("/orders", params=params)
		assert response.status_code == 422
		assert response.json()["error"]["code"] == "VALIDATION_ERROR"
		assert response.json()["error"]["message"]


def test_index_migration_preserves_existing_p1_order(tmp_path):
	database_path = tmp_path / "legacy.db"
	connection = sqlite3.connect(database_path)
	try:
		connection.executescript(
			"""
			CREATE TABLE offerings (
				offering_id INTEGER PRIMARY KEY AUTOINCREMENT,
				name TEXT NOT NULL,
				price_paise INTEGER NOT NULL,
				active INTEGER NOT NULL
			);
			CREATE TABLE orders (
				order_id INTEGER PRIMARY KEY AUTOINCREMENT,
				devotee_name TEXT NOT NULL,
				phone_number TEXT NOT NULL,
				birth_star TEXT NOT NULL,
				booking_date TEXT NOT NULL,
				status TEXT NOT NULL,
				total_paise INTEGER NOT NULL
			);
			CREATE TABLE order_items (
				order_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
				order_id INTEGER NOT NULL,
				offering_id INTEGER NOT NULL,
				quantity INTEGER NOT NULL,
				unit_price_paise INTEGER NOT NULL,
				FOREIGN KEY (order_id) REFERENCES orders(order_id),
				FOREIGN KEY (offering_id) REFERENCES offerings(offering_id)
			);
			INSERT INTO offerings VALUES (1, 'Legacy offering', 3000, 1);
			INSERT INTO orders VALUES
				(42, 'Existing Devotee', '9876543210', 'Ashwini',
				 '2026-10-20', 'BOOKED', 3000);
			INSERT INTO order_items VALUES (7, 42, 1, 1, 3000);
			"""
		)
		connection.commit()
	finally:
		connection.close()

	initialize_database(database_path)
	initialize_database(database_path)

	connection = get_connection(database_path)
	try:
		order = connection.execute(
			"SELECT order_id, devotee_name, total_paise FROM orders WHERE order_id = 42"
		).fetchone()
		assert tuple(order) == (42, "Existing Devotee", 3000)
		assert connection.execute(
			"SELECT COUNT(*) FROM order_items WHERE order_id = 42"
		).fetchone()[0] == 1
		assert [
			row["version"]
			for row in connection.execute("SELECT version FROM schema_migrations")
		] == [1]
		indexes = {
			row["name"] for row in connection.execute("PRAGMA index_list(orders)")
		}
		assert {
			"idx_orders_booking_date_order_id",
			"idx_orders_status_order_id",
			"idx_orders_phone_number_order_id",
		}.issubset(indexes)
	finally:
		connection.close()