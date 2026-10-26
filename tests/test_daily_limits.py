from concurrent.futures import ThreadPoolExecutor
import sqlite3

import app.main as main_module
import app.offerings as offerings_module
import app.orders as orders_module
import pytest
from app.database import get_connection, initialize_database
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def daily_limit_context(tmp_path, monkeypatch):
    database_path = tmp_path / "daily-limits.db"
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
        temple_response = client.post("/temples", json={"name": "Capacity Temple"})
        offering_response = client.post(
            "/offerings",
            json={"name": "Archana", "price": "42.50", "active": True},
        )
        assert temple_response.status_code == 201
        assert offering_response.status_code == 201
        temple_id = temple_response.json()["id"]
        offering_id = offering_response.json()["id"]
        yield client, database_path, temple_id, offering_id


def _map_offering(client, temple_id, offering_id, daily_limit):
    return client.post(
        f"/temples/{temple_id}/offerings",
        json={
            "offering_id": offering_id,
            "active": True,
            "daily_limit": daily_limit,
        },
    )


def _order_payload(temple_id, offering_quantities, booking_date="2026-10-26"):
    return {
        "temple_id": temple_id,
        "devotee_name": "Test Devotee",
        "phone_number": "9876543210",
        "birth_star": "Rohini",
        "booking_date": booking_date,
        "items": [
            {"offering_id": offering_id, "quantity": quantity}
            for offering_id, quantity in offering_quantities
        ],
    }


def test_daily_capacity_counts_quantities_and_allows_exact_limit(daily_limit_context):
    client, database_path, temple_id, offering_id = daily_limit_context
    assert _map_offering(client, temple_id, offering_id, 5).status_code == 201

    first = client.post(
        "/orders", json=_order_payload(temple_id, [(offering_id, 4)])
    )
    over_limit = client.post(
        "/orders", json=_order_payload(temple_id, [(offering_id, 2)])
    )
    final_unit = client.post(
        "/orders", json=_order_payload(temple_id, [(offering_id, 1)])
    )

    assert first.status_code == 201
    assert over_limit.status_code == 409
    assert over_limit.json()["error"]["code"] == "DAILY_LIMIT_EXCEEDED"
    assert over_limit.json()["error"]["message"] == (
        "The daily limit for Archana at Capacity Temple has been exceeded for "
        "2026-10-26."
    )
    assert final_unit.status_code == 201

    connection = get_connection(database_path)
    try:
        booked_quantity = connection.execute(
            """SELECT COALESCE(SUM(order_items.quantity), 0)
               FROM order_items JOIN orders USING (order_id)
               WHERE orders.temple_id = ? AND orders.booking_date = ?
                 AND order_items.offering_id = ?""",
            (temple_id, "2026-10-26", offering_id),
        ).fetchone()[0]
    finally:
        connection.close()
    assert booked_quantity == 5


def test_capacity_is_independent_per_temple_and_preserves_shared_price(
    daily_limit_context,
):
    client, database_path, temple_a, offering_id = daily_limit_context
    temple_b_response = client.post("/temples", json={"name": "Second Temple"})
    temple_b = temple_b_response.json()["id"]
    assert _map_offering(client, temple_a, offering_id, 5).status_code == 201
    assert _map_offering(client, temple_b, offering_id, 3).status_code == 201

    order_a = client.post(
        "/orders", json=_order_payload(temple_a, [(offering_id, 5)])
    )
    order_b = client.post(
        "/orders", json=_order_payload(temple_b, [(offering_id, 3)])
    )
    over_limit_b = client.post(
        "/orders", json=_order_payload(temple_b, [(offering_id, 1)])
    )

    assert order_a.status_code == 201
    assert order_b.status_code == 201
    assert over_limit_b.status_code == 409
    connection = get_connection(database_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM offerings").fetchone()[0] == 1
        assert connection.execute(
            "SELECT price_paise FROM offerings WHERE offering_id = ?", (offering_id,)
        ).fetchone()[0] == 4250
    finally:
        connection.close()


def test_capacity_is_independent_per_booking_date(daily_limit_context):
    client, _, temple_id, offering_id = daily_limit_context
    assert _map_offering(client, temple_id, offering_id, 2).status_code == 201

    first_date = client.post(
        "/orders", json=_order_payload(temple_id, [(offering_id, 2)], "2026-10-26")
    )
    second_date = client.post(
        "/orders", json=_order_payload(temple_id, [(offering_id, 2)], "2026-10-27")
    )
    first_date_exceeded = client.post(
        "/orders", json=_order_payload(temple_id, [(offering_id, 1)], "2026-10-26")
    )

    assert first_date.status_code == 201
    assert second_date.status_code == 201
    assert first_date_exceeded.status_code == 409


def test_null_limit_is_unlimited_and_zero_limit_rejects_orders(daily_limit_context):
    client, _, temple_id, first_offering_id = daily_limit_context
    second_offering_id = client.post(
        "/offerings",
        json={"name": "Zero Limit Offering", "price": "15.00", "active": True},
    ).json()["id"]
    assert _map_offering(client, temple_id, first_offering_id, None).status_code == 201
    assert _map_offering(client, temple_id, second_offering_id, 0).status_code == 201

    unlimited_order = client.post(
        "/orders", json=_order_payload(temple_id, [(first_offering_id, 100_000)])
    )
    zero_limit_order = client.post(
        "/orders", json=_order_payload(temple_id, [(second_offering_id, 1)])
    )

    assert unlimited_order.status_code == 201
    assert zero_limit_order.status_code == 409


def test_invalid_quantities_are_rejected(daily_limit_context):
    client, _, temple_id, offering_id = daily_limit_context
    assert _map_offering(client, temple_id, offering_id, 5).status_code == 201

    for quantity in (0, -1):
        response = client.post(
            "/orders", json=_order_payload(temple_id, [(offering_id, quantity)])
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_repeated_items_for_same_offering_are_counted_together(daily_limit_context):
    client, database_path, temple_id, offering_id = daily_limit_context
    assert _map_offering(client, temple_id, offering_id, 5).status_code == 201

    response = client.post(
        "/orders",
        json=_order_payload(temple_id, [(offering_id, 3), (offering_id, 3)]),
    )

    assert response.status_code == 409
    connection = get_connection(database_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM order_items").fetchone()[0] == 0
    finally:
        connection.close()


def test_over_limit_later_item_rolls_back_entire_order(daily_limit_context):
    client, database_path, temple_id, first_offering = daily_limit_context
    second_offering = client.post(
        "/offerings",
        json={"name": "Second Offering", "price": "10.00", "active": True},
    ).json()["id"]
    assert _map_offering(client, temple_id, first_offering, 10).status_code == 201
    assert _map_offering(client, temple_id, second_offering, 1).status_code == 201
    prior_order = client.post(
        "/orders", json=_order_payload(temple_id, [(second_offering, 1)])
    )
    assert prior_order.status_code == 201

    response = client.post(
        "/orders",
        json=_order_payload(temple_id, [(first_offering, 2), (second_offering, 1)]),
    )

    assert response.status_code == 409
    connection = get_connection(database_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM order_items").fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM order_items WHERE offering_id = ?", (first_offering,)
        ).fetchone()[0] == 0
    finally:
        connection.close()


def test_mapping_failures_do_not_create_orders_or_items(daily_limit_context):
    client, database_path, temple_id, offering_id = daily_limit_context
    unavailable_offering = client.post(
        "/offerings",
        json={"name": "Inactive", "price": "10.00", "active": True},
    ).json()["id"]
    assert _map_offering(client, temple_id, offering_id, 5).status_code == 201
    assert _map_offering(client, temple_id, unavailable_offering, 5).status_code == 201
    client.patch(
        f"/temples/{temple_id}/offerings/{unavailable_offering}",
        json={"active": False},
    )

    unmapped = client.post(
        "/orders", json=_order_payload(temple_id + 1, [(offering_id, 1)])
    )
    inactive = client.post(
        "/orders", json=_order_payload(temple_id, [(unavailable_offering, 1)])
    )

    assert unmapped.status_code == 422
    assert inactive.status_code == 422
    connection = get_connection(database_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM order_items").fetchone()[0] == 0
    finally:
        connection.close()


def test_concurrent_requests_cannot_exceed_daily_capacity(daily_limit_context):
    client, database_path, temple_id, offering_id = daily_limit_context
    assert _map_offering(client, temple_id, offering_id, 5).status_code == 201
    payload = _order_payload(temple_id, [(offering_id, 1)])

    with ThreadPoolExecutor(max_workers=20) as executor:
        responses = list(
            executor.map(lambda _: client.post("/orders", json=payload), range(20))
        )

    statuses = [response.status_code for response in responses]
    assert statuses.count(201) == 5
    assert all(status in (201, 409, 503) for status in statuses)
    connection = get_connection(database_path)
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM orders WHERE temple_id = ? AND booking_date = ?",
            (temple_id, "2026-10-26"),
        ).fetchone()[0] == 5
        assert connection.execute(
            """SELECT SUM(order_items.quantity)
               FROM orders JOIN order_items USING (order_id)
               WHERE orders.temple_id = ? AND orders.booking_date = ?
                 AND order_items.offering_id = ?""",
            (temple_id, "2026-10-26", offering_id),
        ).fetchone()[0] == 5
    finally:
        connection.close()


def test_zero_limit_migration_preserves_existing_mapping_and_items(tmp_path):
    database_path = tmp_path / "legacy-mapping.db"
    connection = sqlite3.connect(database_path)
    try:
        connection.executescript(
            """
            CREATE TABLE temples (temple_id INTEGER PRIMARY KEY, name TEXT NOT NULL);
            CREATE TABLE offerings (
                offering_id INTEGER PRIMARY KEY, name TEXT NOT NULL,
                price_paise INTEGER NOT NULL, active INTEGER NOT NULL
            );
            CREATE TABLE temple_offerings (
                temple_id INTEGER NOT NULL, offering_id INTEGER NOT NULL,
                active INTEGER NOT NULL, daily_limit INTEGER
                    CHECK (daily_limit IS NULL OR daily_limit > 0),
                PRIMARY KEY (temple_id, offering_id),
                FOREIGN KEY (temple_id) REFERENCES temples(temple_id),
                FOREIGN KEY (offering_id) REFERENCES offerings(offering_id)
            );
            CREATE TABLE orders (
                order_id INTEGER PRIMARY KEY, temple_id INTEGER NOT NULL,
                devotee_name TEXT NOT NULL, phone_number TEXT NOT NULL,
                birth_star TEXT NOT NULL, booking_date TEXT NOT NULL,
                status TEXT NOT NULL, total_paise INTEGER NOT NULL,
                UNIQUE (order_id, temple_id),
                FOREIGN KEY (temple_id) REFERENCES temples(temple_id)
            );
            CREATE TABLE order_items (
                order_item_id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL,
                temple_id INTEGER NOT NULL, offering_id INTEGER NOT NULL,
                quantity INTEGER NOT NULL, unit_price_paise INTEGER NOT NULL,
                FOREIGN KEY (order_id, temple_id)
                    REFERENCES orders(order_id, temple_id) ON DELETE CASCADE,
                FOREIGN KEY (temple_id, offering_id)
                    REFERENCES temple_offerings(temple_id, offering_id)
            );
            CREATE TRIGGER trg_order_item_active_temple_offering
            BEFORE INSERT ON order_items
            WHEN NOT EXISTS (
                SELECT 1 FROM temple_offerings AS mapping
                JOIN offerings ON offerings.offering_id = mapping.offering_id
                WHERE mapping.temple_id = NEW.temple_id
                  AND mapping.offering_id = NEW.offering_id
                  AND mapping.active = 1
                  AND offerings.active = 1
            )
            BEGIN
                SELECT RAISE(ABORT, 'offering is not active for this temple');
            END;
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO schema_migrations (version) VALUES (1);
            INSERT INTO temples VALUES (1, 'Legacy Temple');
            INSERT INTO offerings VALUES (2, 'Legacy Offering', 2500, 1);
            INSERT INTO temple_offerings VALUES (1, 2, 1, 5);
            INSERT INTO orders VALUES
                (3, 1, 'Existing Devotee', '9876543210', 'Rohini',
                 '2026-10-26', 'BOOKED', 2500);
            INSERT INTO order_items VALUES (4, 3, 1, 2, 1, 2500);
            """
        )
    finally:
        connection.close()

    initialize_database(database_path)

    connection = get_connection(database_path)
    try:
        assert connection.execute(
            "SELECT daily_limit FROM temple_offerings WHERE temple_id = 1 AND offering_id = 2"
        ).fetchone()[0] == 5
        assert connection.execute(
            "SELECT quantity FROM order_items WHERE order_item_id = 4"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'trigger' "
            "AND name = 'trg_order_item_active_temple_offering'"
        ).fetchone()[0] == 1
        connection.execute(
            "UPDATE temple_offerings SET daily_limit = 0 WHERE temple_id = 1 AND offering_id = 2"
        )
        connection.commit()
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()
