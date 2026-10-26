from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    status: str


class OfferingCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    price: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    active: bool = True


class OfferingResponse(BaseModel):
    id: int
    name: str
    price: Decimal
    active: bool


class OrderItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offering_id: int = Field(gt=0)
    quantity: int = Field(gt=0)


class OrderCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    devotee_name: str = Field(min_length=1, max_length=120)
    phone_number: str = Field(pattern=r"^\+?[0-9]{7,15}$")
    birth_star: str = Field(min_length=1, max_length=50)
    booking_date: date
    items: list[OrderItemCreate] = Field(min_length=1)


class OrderItemResponse(BaseModel):
    offering_id: int
    offering_name: str
    quantity: int
    unit_price: Decimal


class OrderResponse(BaseModel):
    id: int
    devotee_name: str
    phone_number: str
    birth_star: str
    booking_date: date
    status: str
    items: list[OrderItemResponse]
    total: Decimal


class OrderSearchResponse(BaseModel):
    orders: list[OrderResponse]
    page: int
    page_size: int
    total: int
    total_pages: int