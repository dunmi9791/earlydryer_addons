# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""Online pickup booking for the website and the mobile app.

Thin layer over ``earlydryer.logistics.booking``: validation of the input
shape here, every business rule (served areas, fee, slots, limits) there.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field

from odoo.api import Environment
from odoo.tools import consteq

from odoo.addons.fastapi.dependencies import fastapi_endpoint, odoo_env
from odoo.addons.fastapi.models import FastapiEndpoint

router = APIRouter(tags=["pickups"])


def verify_api_key(
    api_key: Annotated[
        str | None, Depends(APIKeyHeader(name="X-Api-Key", auto_error=False))
    ],
    endpoint: Annotated[FastapiEndpoint, Depends(fastapi_endpoint)],
) -> None:
    expected = endpoint.sudo().earlydryer_api_key or ""
    if not api_key or not expected or not consteq(api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key"
        )


Env = Annotated[Environment, Depends(odoo_env)]
secured = [Depends(verify_api_key)]


# ----------------------------------------------------------------------
# Schemas
# ----------------------------------------------------------------------


class Area(BaseModel):
    id: int
    name: str
    city: str = ""


class QuoteRequest(BaseModel):
    area_id: int
    street: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    date: str | None = Field(None, description="First day offered (YYYY-MM-DD).")
    days: int = Field(7, ge=1, le=14)


class Slot(BaseModel):
    key: str
    label: str
    start: str = Field(description="UTC, YYYY-MM-DD HH:MM:SS")
    end: str
    remaining: int


class Quote(BaseModel):
    served: bool
    fee: float
    currency: str
    plant: str
    message: str = ""
    slots: list[Slot] = []


class PickupRequest(BaseModel):
    name: str = Field("", max_length=128)
    phone: str = Field(max_length=32)
    email: str | None = Field(None, max_length=128)
    area_id: int
    street: str = Field(max_length=256)
    landmark: str | None = Field(None, max_length=256)
    gate_instructions: str | None = Field(None, max_length=256)
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)
    slot_key: str = Field(max_length=64, description="A key from the quote.")
    note: str | None = Field(None, max_length=1000)
    return_delivery: bool = False
    notify_opt_in: bool = Field(
        False, description="The customer agrees to order messages (WhatsApp/SMS)."
    )
    client_ref: str | None = Field(
        None,
        max_length=64,
        description="Idempotency key: the same key returns the same pickup.",
    )


class CallbackRequest(BaseModel):
    name: str = Field("", max_length=128)
    phone: str = Field(max_length=32)
    email: str | None = Field(None, max_length=128)
    area_id: int
    street: str = Field(max_length=256)
    landmark: str | None = Field(None, max_length=256)
    note: str | None = Field(None, max_length=1000)
    notify_opt_in: bool = False


class Pickup(BaseModel):
    reference: str
    access_token: str
    state: Literal[
        "draft",
        "scheduled",
        "assigned",
        "en_route",
        "arrived",
        "done",
        "failed",
        "cancelled",
    ]
    state_label: str
    plant: str
    plant_phone: str = ""
    slot_label: str = ""
    slot_start: str = ""
    fee: float
    currency: str
    address: str = ""
    area: str = ""
    cancellable: bool


# ----------------------------------------------------------------------
# Routes
# ----------------------------------------------------------------------


def _booking(env):
    return env["earlydryer.logistics.booking"]


@router.get("/areas", dependencies=secured)
def areas(env: Env) -> list[Area]:
    """Areas served: the address picker."""
    return [Area(**area) for area in _booking(env).public_areas()]


@router.post("/pickups/quote", dependencies=secured)
def quote(env: Env, data: QuoteRequest) -> Quote:
    """Fee and free times of a pickup in an area."""
    return Quote(**_booking(env).quote_pickup(data.model_dump()))


@router.post("/pickups", dependencies=secured, status_code=status.HTTP_201_CREATED)
def book(env: Env, data: PickupRequest) -> Pickup:
    """Book a pickup on a slot from the quote: scheduled at once."""
    payload = dict(data.model_dump(), source="app")
    return Pickup(**_booking(env).book_pickup(payload))


@router.post(
    "/pickups/callback", dependencies=secured, status_code=status.HTTP_201_CREATED
)
def callback(env: Env, data: CallbackRequest) -> Pickup:
    """Area not served or no time suits: Customer Service calls back."""
    payload = dict(data.model_dump(), source="app")
    return Pickup(**_booking(env).request_callback(payload))


@router.get("/pickups/{reference:path}", dependencies=secured)
def get_pickup(
    env: Env, reference: str, token: Annotated[str, Query(max_length=64)]
) -> Pickup:
    return Pickup(**_booking(env).get_pickup(reference, token))


@router.post("/pickups/{reference:path}/cancel", dependencies=secured)
def cancel(
    env: Env, reference: str, token: Annotated[str, Query(max_length=64)]
) -> Pickup:
    return Pickup(**_booking(env).cancel_pickup(reference, token))
