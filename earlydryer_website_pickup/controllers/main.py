# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""Book a pickup on the website (no JavaScript: two server-rendered steps)
and follow it in the portal. Every rule lives in
``earlydryer.logistics.booking``."""

import uuid

from werkzeug.urls import url_encode

from odoo import fields, http
from odoo.exceptions import UserError
from odoo.http import request

from odoo.addons.portal.controllers.portal import CustomerPortal

FORM_FIELDS = (
    "name",
    "phone",
    "email",
    "area_id",
    "street",
    "landmark",
    "gate_instructions",
    "slot_key",
    "note",
    "date",
    "client_ref",
)
# hidden field a person never fills
HONEYPOT = "website_hp"


def _track_url(pickup):
    query = url_encode({"ref": pickup["reference"], "token": pickup["access_token"]})
    return f"/pickup/track?{query}"


class WebsitePickup(http.Controller):
    def _booking(self):
        return request.env["earlydryer.logistics.booking"]

    def _defaults(self):
        values = {}
        if not request.env.user._is_public():
            partner = request.env.user.partner_id
            values.update(
                name=partner.name,
                phone=partner.phone or "",
                email=partner.email or "",
                street=partner.street or "",
                area_id=str(partner.sudo().earlydryer_area_id.id or ""),
                landmark=partner.sudo().earlydryer_landmark or "",
            )
        return values

    def _render_form(self, form, error=None):
        Booking = self._booking()
        # one key per form shown: a double submit books once
        form.setdefault("client_ref", uuid.uuid4().hex)
        quote = None
        if form.get("area_id"):
            try:
                quote = Booking.quote_pickup(
                    {
                        "area_id": form["area_id"],
                        "date": form.get("date") or None,
                    }
                )
            except UserError as exc:
                error = error or exc.args[0]
        return request.render(
            "earlydryer_website_pickup.pickup_page",
            {
                "areas": Booking.public_areas(),
                # call backs are also for areas not served yet
                "all_areas": [
                    {"id": area.id, "name": area.name}
                    for area in request.env["earlydryer.area"]
                    .sudo()
                    .search([], order="name")
                ],
                "form": form,
                "quote": quote,
                "error": error,
                "today": fields.Date.to_string(fields.Date.context_today(Booking)),
                "honeypot": HONEYPOT,
            },
        )

    @http.route("/pickup", type="http", auth="public", website=True, sitemap=True)
    def pickup(self, **post):
        form = dict(self._defaults())
        form.update({key: post[key] for key in FORM_FIELDS if post.get(key)})
        return self._render_form(form)

    def _payload(self, post):
        payload = {key: (post.get(key) or "").strip() for key in FORM_FIELDS}
        payload.update(
            source="website",
            return_delivery=bool(post.get("return_delivery")),
            notify_opt_in=bool(post.get("notify_opt_in")),
            client_ref=payload["client_ref"][:64] or False,
        )
        return payload

    @http.route(
        "/pickup/book", type="http", auth="public", website=True, methods=["POST"]
    )
    def pickup_book(self, **post):
        if post.get(HONEYPOT):
            return request.redirect("/pickup")
        form = {key: post.get(key) or "" for key in FORM_FIELDS if key != "client_ref"}
        try:
            if post.get("callback"):
                result = self._booking().request_callback(self._payload(post))
            else:
                result = self._booking().book_pickup(self._payload(post))
        except UserError as exc:
            request.env.cr.rollback()
            return self._render_form(form, error=exc.args[0])
        return request.redirect(_track_url(result))

    @http.route("/pickup/track", type="http", auth="public", website=True)
    def pickup_track(self, ref=None, token=None, **kw):
        try:
            pickup = self._booking().get_pickup(ref, token)
        except UserError:
            return request.not_found()
        return request.render(
            "earlydryer_website_pickup.pickup_track_page",
            {"pickup": pickup, "message": kw.get("message")},
        )

    @http.route(
        "/pickup/cancel", type="http", auth="public", website=True, methods=["POST"]
    )
    def pickup_cancel(self, ref=None, token=None, **kw):
        query = {"ref": ref or "", "token": token or ""}
        try:
            self._booking().cancel_pickup(ref, token)
        except UserError as exc:
            request.env.cr.rollback()
            query["message"] = exc.args[0]
        return request.redirect(f"/pickup/track?{url_encode(query)}")


class PickupPortal(CustomerPortal):
    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if "pickup_count" in counters:
            values["pickup_count"] = len(
                request.env["earlydryer.logistics.booking"].customer_pickups(
                    request.env.user.partner_id
                )
            )
        return values

    @http.route("/my/pickups", type="http", auth="user", website=True)
    def portal_my_pickups(self, **kw):
        pickups = request.env["earlydryer.logistics.booking"].customer_pickups(
            request.env.user.partner_id
        )
        for pickup in pickups:
            pickup["track_url"] = _track_url(pickup) if pickup["access_token"] else ""
        values = self._prepare_portal_layout_values()
        values.update(pickups=pickups, page_name="pickups")
        return request.render("earlydryer_website_pickup.portal_my_pickups", values)
