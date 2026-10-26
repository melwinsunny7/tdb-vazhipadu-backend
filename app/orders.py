import sqlite3
from decimal import Decimal
from datetime import date

from fastapi import APIRouter, Query, status

from app.database import get_connection
from app.errors import AppError
from app.schemas import (
	OrderCreate,
	OrderItemResponse,
	OrderResponse,
	OrderSearchResponse,
)


router = APIRouter(prefix="/orders", tags=["orders"])


@router.get("", response_model=OrderSearchResponse)
def search_orders(
	booking_date: date | None = None,
	status: str | None = Query(default=None, min_length=1, max_length=30),
	phone_number: str | None = Query(
		default=None, pattern=r"^\+?[0-9]{7,15}$"
	),
	page: int = Query(default=1, ge=1),
	page_size: int = Query(default=20, ge=1, le=100),
) -> OrderSearchResponse:
	filters = []
	parameters = []
	if booking_date is not None:
		filters.append("booking_date = ?")
		parameters.append(booking_date.isoformat())
	if status is not None:
		filters.append("status = ?")
		parameters.append(status)
	if phone_number is not None:
		filters.append("phone_number = ?")
		parameters.append(phone_number)

	where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
	connection = get_connection()
	try:
		total = connection.execute(
			f"SELECT COUNT(*) FROM orders {where_clause}", parameters
		).fetchone()[0]
		offset = (page - 1) * page_size
		order_rows = connection.execute(
			f"SELECT * FROM orders {where_clause} "
			"ORDER BY order_id DESC LIMIT ? OFFSET ?",
			[*parameters, page_size, offset],
		).fetchall()

		items_by_order: dict[int, list[OrderItemResponse]] = {
			row["order_id"]: [] for row in order_rows
		}
		if items_by_order:
			placeholders = ", ".join("?" for _ in items_by_order)
			item_rows = connection.execute(
				"""SELECT order_items.order_id, order_items.offering_id,
				          offerings.name, order_items.quantity,
				          order_items.unit_price_paise
			   FROM order_items
			   JOIN offerings ON offerings.offering_id = order_items.offering_id
			   WHERE order_items.order_id IN ("""
				+ placeholders
				+ ") ORDER BY order_items.order_id, order_items.order_item_id",
				list(items_by_order),
			).fetchall()
			for row in item_rows:
				items_by_order[row["order_id"]].append(
					OrderItemResponse(
						offering_id=row["offering_id"],
						offering_name=row["name"],
						quantity=row["quantity"],
						unit_price=Decimal(row["unit_price_paise"]) / 100,
					)
				)

		orders = [
			OrderResponse(
				id=row["order_id"],
				temple_id=row["temple_id"],
				devotee_name=row["devotee_name"],
				phone_number=row["phone_number"],
				birth_star=row["birth_star"],
				booking_date=row["booking_date"],
				status=row["status"],
				items=items_by_order[row["order_id"]],
				total=Decimal(row["total_paise"]) / 100,
			)
			for row in order_rows
		]
		return OrderSearchResponse(
			orders=orders,
			page=page,
			page_size=page_size,
			total=total,
			total_pages=(total + page_size - 1) // page_size,
		)
	finally:
		connection.close()


@router.post("", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
def create_order(order: OrderCreate) -> OrderResponse:
	connection = get_connection()
	try:
		try:
			connection.execute("BEGIN IMMEDIATE")
			temple = connection.execute(
				"SELECT name FROM temples WHERE temple_id = ?", (order.temple_id,)
			).fetchone()
			if temple is None:
				raise AppError("TEMPLE_NOT_FOUND", "The selected temple does not exist.", 404)
			temple_name = temple["name"]
			priced_items = []
			total_paise = 0
			requested_quantities: dict[int, int] = {}
			for item in order.items:
				requested_quantities[item.offering_id] = (
					requested_quantities.get(item.offering_id, 0) + item.quantity
				)
				offering = connection.execute(
					"""SELECT offerings.offering_id, offerings.name,
					          offerings.price_paise, offerings.active,
					          temple_offerings.active AS temple_active,
					          temples.name AS temple_name
				   FROM offerings
				   JOIN temple_offerings
				     ON temple_offerings.offering_id = offerings.offering_id
			   JOIN temples ON temples.temple_id = temple_offerings.temple_id
				   WHERE offerings.offering_id = ? AND temple_offerings.temple_id = ?""",
					(item.offering_id, order.temple_id),
				).fetchone()
				if offering is None:
					raise AppError(
						"OFFERING_NOT_MAPPED",
						f"Offering {item.offering_id} is not mapped to this temple.",
						status_code=422,
					)
				if not offering["active"] or not offering["temple_active"]:
					raise AppError(
						"INACTIVE_OFFERING",
						f"Offering {item.offering_id} is inactive for this temple.",
						status_code=422,
					)
				unit_price_paise = offering["price_paise"]
				total_paise += unit_price_paise * item.quantity
				priced_items.append((item, offering, unit_price_paise))

			for offering_id, requested_quantity in requested_quantities.items():
				mapping = connection.execute(
					"""SELECT daily_limit FROM temple_offerings
					   WHERE temple_id = ? AND offering_id = ?""",
					(order.temple_id, offering_id),
				).fetchone()
				if mapping is None:
					raise AppError(
						"OFFERING_NOT_MAPPED",
						f"Offering {offering_id} is not mapped to this temple.",
						status_code=422,
					)
				daily_limit = mapping["daily_limit"]
				if daily_limit is None:
					continue
				booked_quantity = connection.execute(
					"""SELECT COALESCE(SUM(order_items.quantity), 0)
					   FROM orders
					   JOIN order_items ON order_items.order_id = orders.order_id
					   WHERE orders.temple_id = ?
					     AND orders.booking_date = ?
					     AND order_items.offering_id = ?""",
					(order.temple_id, order.booking_date.isoformat(), offering_id),
				).fetchone()[0]
				if booked_quantity + requested_quantity > daily_limit:
					raise AppError(
						"DAILY_LIMIT_EXCEEDED",
							f"The daily limit for {offering['name']} at {temple_name} has been exceeded for {order.booking_date.isoformat()}.",
						status_code=409,
					)

			cursor = connection.execute(
				"""INSERT INTO orders
				   (temple_id, devotee_name, phone_number, birth_star,
				    booking_date, status, total_paise)
				   VALUES (?, ?, ?, ?, ?, 'BOOKED', ?)""",
				(
					order.temple_id,
					order.devotee_name,
					order.phone_number,
					order.birth_star,
					order.booking_date.isoformat(),
					total_paise,
				),
			)
			order_id = cursor.lastrowid
			response_items = []
			for item, offering, unit_price_paise in priced_items:
				connection.execute(
					"""INSERT INTO order_items
					   (order_id, temple_id, offering_id, quantity, unit_price_paise)
					   VALUES (?, ?, ?, ?, ?)""",
					(
						order_id,
						order.temple_id,
						item.offering_id,
						item.quantity,
						unit_price_paise,
					),
				)
				response_items.append(
					OrderItemResponse(
						offering_id=item.offering_id,
						offering_name=offering["name"],
						quantity=item.quantity,
						unit_price=Decimal(unit_price_paise) / 100,
					)
				)

			response = OrderResponse(
				id=order_id,
				temple_id=order.temple_id,
				devotee_name=order.devotee_name,
				phone_number=order.phone_number,
				birth_star=order.birth_star,
				booking_date=order.booking_date,
				status="BOOKED",
				items=response_items,
				total=Decimal(total_paise) / 100,
			)
			connection.commit()
			return response
		except AppError:
			connection.rollback()
			raise
		except sqlite3.OperationalError as error:
			connection.rollback()
			if "locked" in str(error).lower() or "busy" in str(error).lower():
				raise AppError(
					"DATABASE_BUSY",
					"Booking is temporarily busy. Please retry the request.",
					status_code=503,
				) from error
			raise
		except Exception:
			connection.rollback()
			raise
	finally:
		connection.close()


@router.get("/{order_id}", response_model=OrderResponse)
def get_order(order_id: int) -> OrderResponse:
	connection = get_connection()
	try:
		order = connection.execute(
			"SELECT * FROM orders WHERE order_id = ?", (order_id,)
		).fetchone()
		if order is None:
			raise AppError("NOT_FOUND", "Order not found.", status_code=404)

		rows = connection.execute(
			"""SELECT order_items.offering_id, offerings.name, order_items.quantity,
					  order_items.unit_price_paise
			   FROM order_items
			   JOIN offerings ON offerings.offering_id = order_items.offering_id
			   WHERE order_items.order_id = ?
			   ORDER BY order_items.order_item_id""",
			(order_id,),
		).fetchall()
		return OrderResponse(
			id=order["order_id"],
			temple_id=order["temple_id"],
			devotee_name=order["devotee_name"],
			phone_number=order["phone_number"],
			birth_star=order["birth_star"],
			booking_date=order["booking_date"],
			status=order["status"],
			items=[
				OrderItemResponse(
					offering_id=row["offering_id"],
					offering_name=row["name"],
					quantity=row["quantity"],
					unit_price=Decimal(row["unit_price_paise"]) / 100,
				)
				for row in rows
			],
			total=Decimal(order["total_paise"]) / 100,
		)
	finally:
		connection.close()