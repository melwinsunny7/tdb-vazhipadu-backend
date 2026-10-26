from decimal import Decimal

from fastapi import APIRouter, status

from app.database import get_connection
from app.errors import AppError
from app.schemas import OrderCreate, OrderItemResponse, OrderResponse


router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
def create_order(order: OrderCreate) -> OrderResponse:
	connection = get_connection()
	try:
		with connection:
			priced_items = []
			total_paise = 0
			for item in order.items:
				offering = connection.execute(
					"SELECT offering_id, name, price_paise, active "
					"FROM offerings WHERE offering_id = ?",
					(item.offering_id,),
				).fetchone()
				if offering is None:
					raise AppError(
						"INVALID_OFFERING",
						f"Offering {item.offering_id} does not exist.",
						status_code=422,
					)
				if not offering["active"]:
					raise AppError(
						"INACTIVE_OFFERING",
						f"Offering {item.offering_id} is inactive.",
						status_code=422,
					)
				unit_price_paise = offering["price_paise"]
				total_paise += unit_price_paise * item.quantity
				priced_items.append((item, offering, unit_price_paise))

			cursor = connection.execute(
				"""INSERT INTO orders
				   (devotee_name, phone_number, birth_star, booking_date, status, total_paise)
				   VALUES (?, ?, ?, ?, 'BOOKED', ?)""",
				(
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
					   (order_id, offering_id, quantity, unit_price_paise)
					   VALUES (?, ?, ?, ?)""",
					(order_id, item.offering_id, item.quantity, unit_price_paise),
				)
				response_items.append(
					OrderItemResponse(
						offering_id=item.offering_id,
						offering_name=offering["name"],
						quantity=item.quantity,
						unit_price=Decimal(unit_price_paise) / 100,
					)
				)

			return OrderResponse(
				id=order_id,
				devotee_name=order.devotee_name,
				phone_number=order.phone_number,
				birth_star=order.birth_star,
				booking_date=order.booking_date,
				status="BOOKED",
				items=response_items,
				total=Decimal(total_paise) / 100,
			)
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