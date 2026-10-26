# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import math
from datetime import timedelta

from odoo import api, fields, models

EARTH_RADIUS_KM = 6371.0088
PARAM_ROAD_FACTOR = "earlydryer_logistics.road_factor"
DEFAULT_ROAD_FACTOR = 1.3
# days of slots offered by a quote
QUOTE_DAYS = 7


class EarlydryerLogisticsQuote(models.AbstractModel):
    """Fee and slots of a pickup or delivery, before booking.

    Used by the backend wizards, the POS and (later) earlydryer_api. Every
    value returned is JSON-safe.
    """

    _name = "earlydryer.logistics.quote"
    _description = "Earlydryer Pickup/Delivery Quote"

    # ------------------------------------------------------------------
    # Distance (extension point: replace with a routing service later)
    # ------------------------------------------------------------------

    @api.model
    def _earlydryer_road_factor(self):
        value = self.env["ir.config_parameter"].sudo().get_param(PARAM_ROAD_FACTOR)
        try:
            return float(value) if value else DEFAULT_ROAD_FACTOR
        except ValueError:
            return DEFAULT_ROAD_FACTOR

    @api.model
    def _earlydryer_point(self, record):
        """``(lat, lng)`` of a partner (its own coordinates, else the centre of
        its area) or of an area; None when unknown."""
        if not record:
            return None
        if record._name == "earlydryer.area":
            return (record.latitude, record.longitude) if record.has_centre else None
        if record.partner_latitude or record.partner_longitude:
            return (record.partner_latitude, record.partner_longitude)
        area = record.earlydryer_area_id if "earlydryer_area_id" in record._fields else False
        return self._earlydryer_point(area) if area else None

    @api.model
    def _earlydryer_haversine_km(self, origin, destination):
        lat1, lng1 = map(math.radians, origin)
        lat2, lng2 = map(math.radians, destination)
        a = (
            math.sin((lat2 - lat1) / 2) ** 2
            + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
        )
        return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))

    @api.model
    def _earlydryer_distance_km(self, origin, destination):
        """Estimated road distance in km between two ``(lat, lng)`` points:
        straight-line (haversine) distance times the road factor (setting,
        default 1.3). None when a point is unknown.

        The single place to plug a routing service (OSRM, a paid API...).
        """
        if not origin or not destination:
            return None
        straight = self._earlydryer_haversine_km(origin, destination)
        return round(straight * self._earlydryer_road_factor(), 2)

    # ------------------------------------------------------------------
    # Fees
    # ------------------------------------------------------------------

    @api.model
    def _earlydryer_fee(self, zone, stop_type, distance_km, express, order_amount):
        """``(fee, breakdown, served, message, below_minimum)`` of a zone."""
        currency = zone.currency_id or self.env.company.currency_id
        breakdown = []
        _ = self.env._
        if stop_type == "pickup":
            if zone.pickup_fee:
                breakdown.append({"label": _("Pickup fee"), "amount": zone.pickup_fee})
            return (
                currency.round(zone.pickup_fee),
                breakdown,
                True,
                "",
                False,
            )
        message = ""
        if zone.fee_mode == "distance":
            if distance_km is None:
                fee = zone.base_fee
                message = _(
                    "Distance unknown (no GPS for the address or its area): base "
                    "fee only, confirm the fee with the customer."
                )
                breakdown.append({"label": _("Base fee"), "amount": zone.base_fee})
            else:
                if zone.max_km and distance_km > zone.max_km:
                    return (
                        0.0,
                        [],
                        False,
                        _(
                            "%(km).1f km is beyond the %(max).1f km served by zone "
                            "%(zone)s.",
                            km=distance_km,
                            max=zone.max_km,
                            zone=zone.name,
                        ),
                        False,
                    )
                per_km = currency.round(zone.fee_per_km * distance_km)
                fee = zone.base_fee + per_km
                breakdown += [
                    {"label": _("Base fee"), "amount": zone.base_fee},
                    {
                        "label": _("%(km).1f km", km=distance_km),
                        "amount": per_km,
                    },
                ]
        else:
            fee = zone.flat_fee
            breakdown.append({"label": _("Delivery fee"), "amount": zone.flat_fee})
        if zone.free_over_amount and order_amount >= zone.free_over_amount:
            breakdown.append(
                {
                    "label": _(
                        "Free delivery over %(amount)s", amount=zone.free_over_amount
                    ),
                    "amount": -fee,
                }
            )
            fee = 0.0
        if express and zone.express_fee:
            fee += zone.express_fee
            breakdown.append({"label": _("Express"), "amount": zone.express_fee})
        below_minimum = bool(
            zone.min_order_amount and order_amount < zone.min_order_amount
        )
        if below_minimum:
            message = " ".join(
                filter(
                    None,
                    [
                        message,
                        _(
                            "Order below the %(minimum)s minimum of zone %(zone)s: "
                            "a Branch Manager must approve the delivery.",
                            minimum=zone.min_order_amount,
                            zone=zone.name,
                        ),
                    ],
                )
            )
        return currency.round(fee), breakdown, True, message, below_minimum

    @api.model
    def quote(
        self,
        partner,
        address_partner,
        branch,
        stop_type,
        date,
        express=False,
        order_amount=0.0,
        days=QUOTE_DAYS,
    ):
        """Fee and available slots of a pickup or delivery.

        :param partner: customer ``res.partner``
        :param address_partner: address used (a delivery contact), or the
            customer itself when empty
        :param branch: ``earlydryer.branch`` serving the stop
        :param stop_type: ``pickup`` or ``delivery``
        :param date: first day of the slots offered (``date`` or string)
        :param express: same-day / express delivery (adds the zone's express fee)
        :param order_amount: order value (free-delivery threshold, minimum)
        :returns: ``{"served", "zone_id", "zone_name", "area_id", "fee",
            "fee_breakdown", "distance_km", "below_minimum",
            "available_slots", "message"}``
        """
        address = address_partner or partner
        area = address.earlydryer_area_id if address else self.env["earlydryer.area"]
        zone = self.env["earlydryer.delivery.zone"].sudo()._earlydryer_find(branch, area)
        origin = self._earlydryer_point(branch.partner_id)
        destination = self._earlydryer_point(address)
        distance_km = self._earlydryer_distance_km(origin, destination)
        result = {
            "served": False,
            "zone_id": zone.id or False,
            "zone_name": zone.name or "",
            "area_id": area.id or False,
            "fee": 0.0,
            "fee_breakdown": [],
            "distance_km": distance_km,
            "below_minimum": False,
            "available_slots": [],
            "message": "",
        }
        date = fields.Date.to_date(date) if date else fields.Date.context_today(self)
        slots = self.env["earlydryer.logistics.slot.template"].available_slots(
            branch,
            stop_type,
            date,
            date + timedelta(days=max(days, 1) - 1),
            zone=zone or None,
        )
        result["available_slots"] = slots
        if not area:
            result["message"] = self.env._(
                "The address has no area: set its area to get a fee."
            )
            return result
        if not zone:
            result["message"] = self.env._(
                "Area %(area)s is not served by %(branch)s: a Branch Manager must "
                "set a manual fee.",
                area=area.name,
                branch=branch.display_name,
            )
            return result
        fee, breakdown, served, message, below_minimum = self._earlydryer_fee(
            zone, stop_type, distance_km, express, order_amount or 0.0
        )
        result.update(
            served=served,
            fee=fee if served else 0.0,
            fee_breakdown=breakdown,
            message=message,
            below_minimum=below_minimum,
        )
        return result
