from decimal import Decimal

from fastapi import APIRouter, status

from app.database import get_connection
from app.errors import AppError
from app.schemas import (
	OfferingCreate,
	OfferingResponse,
	TempleCreate,
	TempleOfferingMappingCreate,
	TempleOfferingResponse,
	TempleOfferingMappingUpdate,
	TempleResponse,
)


router = APIRouter(prefix="/offerings", tags=["offerings"])
temples_router = APIRouter(prefix="/temples", tags=["temples"])


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


@temples_router.post("", response_model=TempleResponse, status_code=201)
def create_temple(temple: TempleCreate) -> TempleResponse:
	connection = get_connection()
	try:
		with connection:
			cursor = connection.execute(
				"INSERT INTO temples (name) VALUES (?)", (temple.name,)
			)
			return TempleResponse(id=cursor.lastrowid, name=temple.name)
	except Exception as error:
		if "UNIQUE constraint failed" in str(error):
			raise AppError("DUPLICATE_TEMPLE", "A temple with that name already exists.", 409)
		raise
	finally:
		connection.close()


@temples_router.get("", response_model=list[TempleResponse])
def list_temples() -> list[TempleResponse]:
	connection = get_connection()
	try:
		rows = connection.execute(
			"SELECT temple_id, name FROM temples ORDER BY temple_id"
		).fetchall()
		return [TempleResponse(id=row["temple_id"], name=row["name"]) for row in rows]
	finally:
		connection.close()


@temples_router.post("/{temple_id}/offerings", status_code=201)
def map_offering_to_temple(
	temple_id: int, mapping: TempleOfferingMappingCreate
) -> dict[str, int | bool | None]:
	connection = get_connection()
	try:
		with connection:
			temple = connection.execute(
				"SELECT 1 FROM temples WHERE temple_id = ?", (temple_id,)
			).fetchone()
			if temple is None:
				raise AppError("TEMPLE_NOT_FOUND", "Temple not found.", 404)
			offering = connection.execute(
				"SELECT 1 FROM offerings WHERE offering_id = ?", (mapping.offering_id,)
			).fetchone()
			if offering is None:
				raise AppError("OFFERING_NOT_FOUND", "Offering not found.", 404)
			connection.execute(
				"""INSERT INTO temple_offerings
				   (temple_id, offering_id, active, daily_limit) VALUES (?, ?, ?, ?)""",
				(temple_id, mapping.offering_id, int(mapping.active), mapping.daily_limit),
			)
			return {
				"temple_id": temple_id,
				"offering_id": mapping.offering_id,
				"active": mapping.active,
				"daily_limit": mapping.daily_limit,
			}
	except Exception as error:
		if "UNIQUE constraint failed" in str(error):
			raise AppError(
				"DUPLICATE_TEMPLE_OFFERING",
				"The offering is already mapped to this temple.",
				409,
			)
		raise
	finally:
		connection.close()


@temples_router.get(
	"/{temple_id}/offerings", response_model=list[TempleOfferingResponse]
)
def list_temple_offerings(temple_id: int) -> list[TempleOfferingResponse]:
	connection = get_connection()
	try:
		temple = connection.execute(
			"SELECT 1 FROM temples WHERE temple_id = ?", (temple_id,)
		).fetchone()
		if temple is None:
			raise AppError("TEMPLE_NOT_FOUND", "Temple not found.", 404)
		rows = connection.execute(
			"""SELECT temple_offerings.temple_id, offerings.offering_id,
			          offerings.name, offerings.price_paise,
			          temple_offerings.active, temple_offerings.daily_limit
		   FROM temple_offerings
		   JOIN offerings ON offerings.offering_id = temple_offerings.offering_id
		   WHERE temple_offerings.temple_id = ?
		   ORDER BY offerings.offering_id""",
			(temple_id,),
		).fetchall()
		return [
			TempleOfferingResponse(
				temple_id=row["temple_id"],
				offering_id=row["offering_id"],
				name=row["name"],
				price=Decimal(row["price_paise"]) / 100,
				active=bool(row["active"]),
				daily_limit=row["daily_limit"],
			)
			for row in rows
		]
	finally:
		connection.close()


@temples_router.patch("/{temple_id}/offerings/{offering_id}")
def update_temple_offering_mapping(
	temple_id: int, offering_id: int, update: TempleOfferingMappingUpdate
) -> dict[str, int | bool | None]:
	changes = update.model_dump(exclude_unset=True)
	if not changes:
		raise AppError("EMPTY_UPDATE", "At least one mapping field is required.", 422)
	if "active" in changes and changes["active"] is None:
		raise AppError("INVALID_ACTIVE", "The active field cannot be null.", 422)

	connection = get_connection()
	try:
		with connection:
			mapping = connection.execute(
				"""SELECT active, daily_limit FROM temple_offerings
				   WHERE temple_id = ? AND offering_id = ?""",
				(temple_id, offering_id),
			).fetchone()
			if mapping is None:
				raise AppError("TEMPLE_OFFERING_NOT_FOUND", "Mapping not found.", 404)
			assignments = ", ".join(f"{column} = ?" for column in changes)
			connection.execute(
				f"UPDATE temple_offerings SET {assignments} "
				"WHERE temple_id = ? AND offering_id = ?",
				[*[int(value) if column == "active" else value
				  for column, value in changes.items()], temple_id, offering_id],
			)
			updated = connection.execute(
				"""SELECT active, daily_limit FROM temple_offerings
				   WHERE temple_id = ? AND offering_id = ?""",
				(temple_id, offering_id),
			).fetchone()
			return {
				"temple_id": temple_id,
				"offering_id": offering_id,
				"active": bool(updated["active"]),
				"daily_limit": updated["daily_limit"],
			}
	finally:
		connection.close()