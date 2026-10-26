from decimal import Decimal

from fastapi import APIRouter, status

from app.database import get_connection
from app.schemas import OfferingCreate, OfferingResponse


router = APIRouter(prefix="/offerings", tags=["offerings"])


def _offering_response(row) -> OfferingResponse:
	return OfferingResponse(
		id=row["offering_id"],
		name=row["name"],
		price=Decimal(row["price_paise"]) / 100,
		active=bool(row["active"]),
	)


@router.post("", response_model=OfferingResponse, status_code=status.HTTP_201_CREATED)
def create_offering(offering: OfferingCreate) -> OfferingResponse:
	price_paise = int(offering.price * 100)
	connection = get_connection()
	try:
		with connection:
			cursor = connection.execute(
				"INSERT INTO offerings (name, price_paise, active) VALUES (?, ?, ?)",
				(offering.name, price_paise, int(offering.active)),
			)
			row = connection.execute(
				"SELECT * FROM offerings WHERE offering_id = ?",
				(cursor.lastrowid,),
			).fetchone()
			return _offering_response(row)
	finally:
		connection.close()


@router.get("", response_model=list[OfferingResponse])
def list_offerings() -> list[OfferingResponse]:
	connection = get_connection()
	try:
		rows = connection.execute(
			"SELECT * FROM offerings ORDER BY offering_id"
		).fetchall()
		return [_offering_response(row) for row in rows]
	finally:
		connection.close()