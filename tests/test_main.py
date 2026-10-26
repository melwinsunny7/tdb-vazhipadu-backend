from decimal import Decimal

import app.main as main_module
import app.offerings as offerings_module
import app.orders as orders_module
from app.database import get_connection, initialize_database
from fastapi.testclient import TestClient

from app.main import app


def test_health_endpoint_returns_ok(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "health.db"
    monkeypatch.setattr(
        main_module, "initialize_database", lambda: initialize_database(database_path)
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
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_order_total_is_calculated_from_offering_prices(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "data" / "orders.db"
    monkeypatch.setattr(
        main_module, "initialize_database", lambda: initialize_database(database_path)
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
        temple = client.post("/temples", json={"name": "Main Temple"})
        pushpanjali = client.post(
            "/offerings",
            json={"name": "Pushpanjali", "price": "30.00", "active": True},
        )
        archana = client.post(
            "/offerings",
            json={"name": "Archana", "price": "50.00", "active": True},
        )
        assert pushpanjali.status_code == 201
        assert archana.status_code == 201
        for offering_response in (pushpanjali, archana):
            mapping_response = client.post(
                f"/temples/{temple.json()['id']}/offerings",
                json={"offering_id": offering_response.json()["id"], "active": True},
            )
            assert mapping_response.status_code == 201

        response = client.post(
            "/orders",
            json={
                "temple_id": temple.json()["id"],
                "devotee_name": "Ananya Menon",
                "phone_number": "9876543210",
                "birth_star": "Ashwini",
                "booking_date": "2026-10-26",
                "items": [
                    {"offering_id": pushpanjali.json()["id"], "quantity": 2},
                    {"offering_id": archana.json()["id"], "quantity": 1},
                ],
            },
        )

    assert response.status_code == 201
    assert Decimal(str(response.json()["total"])) == Decimal("110.00")