# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import logging
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError

_logger = logging.getLogger(__name__)

DEFAULT_TERMS = (
    "Items not collected within 14 days of being ready are kept at the owner's risk."
)
# promised times are estimated offline within this horizon of public holidays
CALENDAR_LEAVE_DAYS = 120


class PosConfig(models.Model):
    _inherit = "pos.config"

    earlydryer_enabled = fields.Boolean(
        string="Earlydryer Laundry Counter",
        help="Laundry intake, garment tags and collection on this till. Needs "
        "a plant, a price list of that plant and a Customer Account payment "
        "method that identifies the customer.",
    )
    earlydryer_walkin_partner_id = fields.Many2one(
        "res.partner",
        string="Walk-in Customer",
        help="Anonymous contact used for retail-only sales. Laundry intake "
        "always needs a real customer (name and phone).",
    )
    earlydryer_tag_range_size = fields.Integer(
        string="Tag Range Size",
        default=500,
        help="Tag numbers taken from the plant's sequence in one block for "
        "offline printing.",
    )
    earlydryer_tag_range_low_pct = fields.Integer(
        string="Top-up Below (%)",
        default=20,
        help="A new tag range is allocated when fewer than this share of the "
        "till's numbers is left (checked at session opening and whenever the "
        "till is online).",
    )
    earlydryer_label_width_mm = fields.Float(
        string="Label Width (mm)",
        default=50,
        help="Garment tag size for printing from the browser.",
    )
    earlydryer_label_height_mm = fields.Float(string="Label Height (mm)", default=25)
    earlydryer_print_tags_auto = fields.Boolean(
        string="Print Tags after Payment", default=True
    )
    earlydryer_receipt_terms = fields.Text(
        string="Receipt Terms",
        default=DEFAULT_TERMS,
        translate=True,
        help="Printed at the bottom of laundry receipts. PLACEHOLDER wording: "
        "Earlydryer must confirm it.",
    )
    earlydryer_collection_cache_days = fields.Integer(
        string="Collection Cache (days)",
        default=30,
        help="Ready and uncollected jobs of the plant from the last days kept on "
        "the till, so collection works offline.",
    )

    @api.constrains(
        "earlydryer_enabled",
        "earlydryer_branch_id",
        "pricelist_id",
        "payment_method_ids",
        "earlydryer_tag_range_size",
        "earlydryer_tag_range_low_pct",
    )
    def _check_earlydryer_enabled(self):
        for config in self.filtered("earlydryer_enabled"):
            branch = config.earlydryer_branch_id
            if not branch:
                raise ValidationError(
                    self.env._(
                        "%(pos)s: choose the plant of an Earlydryer laundry counter.",
                        pos=config.display_name,
                    )
                )
            if config.pricelist_id.earlydryer_branch_id != branch:
                raise ValidationError(
                    self.env._(
                        "%(pos)s: the default price list must be one of plant "
                        "%(branch)s (use Sync POS Price Lists on the plant).",
                        pos=config.display_name,
                        branch=branch.display_name,
                    )
                )
            if not config._earlydryer_account_methods():
                raise ValidationError(
                    self.env._(
                        "%(pos)s: add a Customer Account payment method (no "
                        "journal) with Identify Customer, so balances go on the "
                        "customer's account.",
                        pos=config.display_name,
                    )
                )
            if config.earlydryer_tag_range_size < 1 or not (
                0 <= config.earlydryer_tag_range_low_pct <= 100
            ):
                raise ValidationError(
                    self.env._(
                        "%(pos)s: the tag range size must be positive and the "
                        "top-up threshold between 0 and 100%%.",
                        pos=config.display_name,
                    )
                )

    def _earlydryer_account_methods(self):
        """Customer-account methods (19: no journal, type ``pay_later``) that
        identify the customer, so the session posts per-customer receivables."""
        self.ensure_one()
        return self.payment_method_ids.filtered(
            lambda method: method.type == "pay_later" and method.split_transactions
        )

    # ------------------------------------------------------------------
    # Tag ranges
    # ------------------------------------------------------------------

    def _earlydryer_top_up_tag_ranges(self):
        """Allocate a new range to the tills running low (or without one).

        Uses this till's range size and threshold; the tagging module's own
        top-up (session opening, daily cron) uses the last range size.
        :returns: the new ranges
        """
        Range = self.env["earlydryer.tag.range"].sudo()
        new = Range.browse()
        for config in self.sudo().filtered("earlydryer_enabled"):
            branch = config.earlydryer_branch_id
            if branch.tag_mode != "printed":
                continue
            active = Range.search(
                [("pos_config_id", "=", config.id), ("state", "=", "active")]
            )
            left = sum(active.mapped("remaining_count"))
            size = config.earlydryer_tag_range_size or 500
            if active and left * 100 >= size * config.earlydryer_tag_range_low_pct:
                continue
            new |= Range._earlydryer_allocate_range(branch, config, size=size)
            _logger.info(
                "Tag range of %s numbers allocated to %s (%s left).",
                size,
                config.display_name,
                left,
            )
        return new

    # ------------------------------------------------------------------
    # Data for the till
    # ------------------------------------------------------------------

    def _earlydryer_check_till_access(self):
        """The user may use this till: branch visible, session open."""
        self.ensure_one()
        self.check_access("read")
        branch = self.earlydryer_branch_id
        if not self.earlydryer_enabled or not branch:
            raise AccessError(
                self.env._(
                    "%(pos)s is not an Earlydryer laundry counter.",
                    pos=self.display_name,
                )
            )
        user = self.env.user
        if not self.env.su and branch not in user._earlydryer_allowed_branches():
            raise AccessError(
                self.env._(
                    "You do not work on plant %(branch)s.", branch=branch.display_name
                )
            )
        if not self.env.su and not self.current_session_id:
            raise AccessError(
                self.env._("%(pos)s has no open session.", pos=self.display_name)
            )
        return True

    def _earlydryer_branch_data(self):
        self.ensure_one()
        branch = self.earlydryer_branch_id.sudo()
        partner = branch.partner_id
        address = ", ".join(
            part for part in (partner.street, partner.street2, partner.city) if part
        )
        return {
            "id": branch.id,
            "name": branch.name,
            "code": branch.code,
            "address": address,
            "phone": partner.phone or "",
            "tag_mode": branch.tag_mode,
            "tag_prefix": branch.tag_prefix or "",
            "tag_check_digit": branch.tag_check_digit,
            "tag_preprinted_pattern": branch.tag_preprinted_pattern or "",
        }

    def _earlydryer_calendar_data(self):
        """Working hours of the plant, enough to estimate a promise offline."""
        self.ensure_one()
        calendar = self.earlydryer_branch_id.sudo().resource_calendar_id
        if not calendar:
            return False
        now = fields.Datetime.now()
        leaves = (
            self.env["resource.calendar.leaves"]
            .sudo()
            .search(
                [
                    ("calendar_id", "in", [calendar.id, False]),
                    ("resource_id", "=", False),
                    ("date_to", ">=", now),
                    ("date_from", "<=", now + timedelta(days=CALENDAR_LEAVE_DAYS)),
                ]
            )
        )
        return {
            "tz": calendar.tz or "UTC",
            "two_weeks": calendar.two_weeks_calendar,
            "attendances": [
                {
                    "dayofweek": int(attendance.dayofweek),
                    "hour_from": attendance.hour_from,
                    "hour_to": attendance.hour_to,
                    "week_type": attendance.week_type or False,
                }
                for attendance in calendar.attendance_ids
                # 19: no dated attendances; skip lunch breaks and section rows
                if attendance.day_period != "lunch" and not attendance.display_type
            ],
            # naive UTC strings, like every datetime the POS loads
            "leaves": [
                [
                    fields.Datetime.to_string(leave.date_from),
                    fields.Datetime.to_string(leave.date_to),
                ]
                for leave in leaves
            ],
        }

    def _earlydryer_pos_payload(self, with_collection=True):
        """Plain values the till keeps for offline intake and collection."""
        self.ensure_one()
        Range = self.env["earlydryer.tag.range"].sudo()
        ranges = Range.search(
            [("pos_config_id", "=", self.id), ("state", "=", "active")],
            order="start_number",
        )
        catalog = self.env["earlydryer.catalog"]
        settlement = self.env.ref(
            "earlydryer_pos.product_settlement", raise_if_not_found=False
        )
        payload = {
            "branch": self._earlydryer_branch_data(),
            "ranges": ranges._earlydryer_pos_data(),
            "calendar": self._earlydryer_calendar_data(),
            "express_product_id": catalog.get_express_product().id,
            "settlement_product_id": settlement.id if settlement else False,
            "account_method_ids": self._earlydryer_account_methods().ids,
            "credit_fallback_employee_ids": (
                self._earlydryer_credit_fallback_employees()
            ),
            "generated_at": fields.Datetime.to_string(fields.Datetime.now()),
        }
        if with_collection:
            payload["collection"] = self.env[
                "laundry.job"
            ]._earlydryer_pos_collection_cache(
                self.earlydryer_branch_id, self.earlydryer_collection_cache_days
            )
        return payload

    def _earlydryer_manager_users(self):
        """Who is told about problems of this till: the plant manager, or the
        Branch Managers allowed on the plant."""
        self.ensure_one()
        branch = self.earlydryer_branch_id.sudo()
        if branch.manager_id and branch.manager_id.active:
            return branch.manager_id
        group = self.env.ref("earlydryer_base.group_branch_manager").sudo()
        return group.all_user_ids.filtered(
            lambda user: user.active
            and not user.share
            and branch in user.earlydryer_branch_ids
        )

    def _earlydryer_credit_fallback_employees(self):
        """Employees who may release on credit when no credit rule matches
        (laundry_order: a Branch Manager)."""
        self.ensure_one()
        group = self.env.ref("earlydryer_base.group_branch_manager").sudo()
        employees = (
            self.env["hr.employee"]
            .sudo()
            .search(
                [
                    ("user_id", "in", group.all_user_ids.ids),
                    ("company_id", "in", [self.company_id.id, False]),
                ]
            )
        )
        return employees.ids

    @api.model
    def _load_pos_data_read(self, records, config):
        read_records = super()._load_pos_data_read(records, config)
        if read_records and config.earlydryer_enabled:
            try:
                config._earlydryer_top_up_tag_ranges()
            except Exception:  # pylint: disable=broad-except  # never block the till
                _logger.exception(
                    "Tag range top-up failed for %s.", config.display_name
                )
            read_records[0]["_earlydryer"] = config._earlydryer_pos_payload()
        return read_records

    def earlydryer_pos_refresh(self, with_collection=True):
        """RPC of the till when online: top up the tag ranges, return fresh
        ranges, rules context and collection cache."""
        self.ensure_one()
        self._earlydryer_check_till_access()
        self._earlydryer_top_up_tag_ranges()
        return self._earlydryer_pos_payload(with_collection=with_collection)

    # ------------------------------------------------------------------
    # Demo data
    # ------------------------------------------------------------------

    def _earlydryer_load_demo_orders(self):
        """Demo only: sync a paid and a partly paid intake the way the POS
        does, then close the session."""
        self.ensure_one()
        ref = self.env.ref
        # as the administrator: OdooBot has no Point of Sale rights
        config = self.with_user(ref("base.user_admin"))
        if not config.current_session_id:
            config.open_ui()
        session = config.current_session_id
        catalog = config.env["earlydryer.catalog"]

        def product(category, service):
            return catalog.get_laundry_product(
                ref(f"earlydryer_service_catalog.garment_category_{category}"),
                ref(f"earlydryer_service_catalog.service_type_{service}"),
            )

        cash = ref("earlydryer_service_catalog.pos_payment_method_cash_p1")
        account = ref("earlydryer_pos.pos_payment_method_account")
        beads = ref("earlydryer_service_catalog.surcharge_beads")
        employee = ref("earlydryer_laundry_order.employee_front_desk_p1")
        orders = [
            (
                ref("earlydryer_laundry_order.partner_customer_adaeze"),
                [
                    (product("shirt", "wash_iron"), 3, None, "White"),
                    (product("suit", "dry_cleaning"), 1, None, "Navy"),
                ],
                1.0,
            ),
            (
                ref("earlydryer_laundry_order.partner_customer_kabir"),
                [(product("agbada", "dry_cleaning"), 1, beads, "Cream")],
                0.4,
            ),
        ]
        branch = config.earlydryer_branch_id
        tag_range = (
            self.env["earlydryer.tag.range"]
            .sudo()
            .search(
                [("pos_config_id", "=", config.id), ("state", "=", "active")], limit=1
            )
        )
        next_number = [tag_range.next_number]

        def codes(garment, qty):
            # printed at the till from its range, like the browser does
            pieces = int(qty) * (
                garment.earlydryer_garment_category_id.piece_count or 1
            )
            if not tag_range or branch.tag_mode != "printed":
                return False
            first = next_number[0]
            next_number[0] += pieces
            return ",".join(
                self.env["earlydryer.tag.code"].format_number(branch, first + i)
                for i in range(pieces)
            )

        payloads = []
        for number, (partner, garments, cash_share) in enumerate(orders, start=1):
            lines = []
            for garment, qty, surcharge, colour in garments:
                uuid = f"ed-demo-{number}-{garment.id}"
                price = config.pricelist_id._get_product_price(garment, qty)
                lines.append(
                    config._earlydryer_ui_line(
                        garment,
                        qty,
                        price,
                        uuid,
                        earlydryer_colour=colour,
                        earlydryer_tag_codes=codes(garment, qty),
                    )
                )
                if surcharge:
                    sur_price = config.pricelist_id._get_product_price(
                        surcharge.product_id, qty
                    )
                    lines.append(
                        config._earlydryer_ui_line(
                            surcharge.product_id,
                            qty,
                            sur_price,
                            f"{uuid}-s",
                            earlydryer_parent_line_uuid=uuid,
                            earlydryer_surcharge_id=surcharge.id,
                        )
                    )
            total = sum(line[2]["price_subtotal_incl"] for line in lines)
            paid = round(total * cash_share, 2)
            payments = [(0, 0, {"amount": paid, "payment_method_id": cash.id})]
            if total - paid:
                payments.append(
                    (0, 0, {"amount": total - paid, "payment_method_id": account.id})
                )
            payloads.append(
                {
                    "uuid": f"ed-demo-order-{config.id}-{number}",
                    "name": f"Demo {number}",
                    "session_id": session.id,
                    "partner_id": partner.id,
                    "employee_id": employee.id,
                    "pricelist_id": config.pricelist_id.id,
                    "user_id": config.env.uid,
                    "lines": lines,
                    "payment_ids": payments,
                    "amount_paid": total,
                    "amount_total": total,
                    "amount_tax": 0.0,
                    "amount_return": 0.0,
                    "date_order": fields.Datetime.to_string(fields.Datetime.now()),
                    "state": "paid",
                    "to_invoice": False,
                    "last_order_preparation_change": "{}",
                }
            )
        config.env["pos.order"].sync_from_ui(payloads)
        # close the till again: an open session blocks catalogue changes
        # (archiving products) and the closing entry shows the customer
        # account receivables
        cash_total = sum(
            session.order_ids.payment_ids.filtered(
                lambda payment: payment.payment_method_id.is_cash_count
            ).mapped("amount")
        )
        session.post_closing_cash_details(cash_total)
        session.close_session_from_ui()
        return True

    @api.model
    def _earlydryer_ui_line(self, product, qty, price, uuid, **extra):
        """A pos.order.line command as the till sends it (no taxes)."""
        return (
            0,
            0,
            {
                "uuid": uuid,
                "product_id": product.id,
                "qty": qty,
                "price_unit": price,
                "price_subtotal": price * qty,
                "price_subtotal_incl": price * qty,
                "discount": 0.0,
                "tax_ids": [(6, 0, [])],
                **extra,
            },
        )
