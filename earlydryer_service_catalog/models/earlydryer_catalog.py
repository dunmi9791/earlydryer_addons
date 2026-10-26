# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import logging
from datetime import date as date_type
from datetime import datetime, timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class EarlydryerCatalog(models.AbstractModel):
    """Pricing and turnaround service of the Earlydryer catalogue.

    No table: call it as ``env["earlydryer.catalog"].price_item(...)``. Order,
    POS, API and corporate modules must use these methods instead of
    re-implementing pricing, so that every channel prices the same way.
    """

    _name = "earlydryer.catalog"
    _description = "Earlydryer Catalogue Service"

    # ------------------------------------------------------------------
    # Products
    # ------------------------------------------------------------------

    @api.model
    def get_laundry_product(self, category, service_type):
        """Return the active laundry ``product.product`` of a category × service.

        :param category: ``earlydryer.garment.category`` record
        :param service_type: ``earlydryer.service.type`` record
        :raises UserError: when the combination is not sold
        """
        product = self.env["product.product"].search(
            [
                ("earlydryer_kind", "=", "laundry"),
                ("earlydryer_garment_category_id", "=", category.id),
                ("earlydryer_service_type_id", "=", service_type.id),
                ("company_id", "in", [self.env.company.id, False]),
            ],
            limit=1,
        )
        if not product:
            raise UserError(
                self.env._(
                    "Earlydryer does not sell %(service)s for %(category)s.",
                    service=service_type.display_name,
                    category=category.display_name,
                )
            )
        return product

    @api.model
    def get_express_product(self):
        """Return the product used for express order lines."""
        return self.env.ref("earlydryer_service_catalog.product_express")

    @api.model
    def _generate_laundry_products(
        self, categories, service_types, list_price=0.0, taxes=None, income_account=None
    ):
        """Create the missing laundry products of ``categories`` × ``service_types``.

        ``allowed_category_ids`` of each service type is respected. Existing
        products of a combination (archived ones included) are never touched.

        :returns: tuple ``(created product.template recordset, skipped count)``
        """
        Template = self.env["product.template"]
        existing = Template.with_context(active_test=False).search_read(
            [
                ("earlydryer_kind", "=", "laundry"),
                ("earlydryer_garment_category_id", "in", categories.ids),
                ("earlydryer_service_type_id", "in", service_types.ids),
                ("company_id", "in", [self.env.company.id, False]),
            ],
            ["earlydryer_garment_category_id", "earlydryer_service_type_id"],
        )
        existing_keys = {
            (
                rec["earlydryer_garment_category_id"][0],
                rec["earlydryer_service_type_id"][0],
            )
            for rec in existing
        }
        vals_list = []
        skipped = 0
        for service in service_types:
            allowed = categories.filtered(service._allows_category)
            if not allowed:
                continue
            pos_category = service._ensure_pos_category()
            for category in allowed:
                if (category.id, service.id) in existing_keys:
                    skipped += 1
                    continue
                vals = {
                    "name": Template._earlydryer_laundry_name(category, service),
                    "default_code": Template._earlydryer_laundry_code(
                        category, service
                    ),
                    "list_price": list_price,
                    "earlydryer_garment_category_id": category.id,
                    "earlydryer_service_type_id": service.id,
                    "taxes_id": [fields.Command.set(taxes.ids if taxes else [])],
                    **Template._earlydryer_service_product_vals(
                        "laundry", pos_category
                    ),
                }
                if category.image_128:
                    vals["image_1920"] = category.image_128
                if income_account:
                    vals["property_account_income_id"] = income_account.id
                vals_list.append(vals)
        return Template.create(vals_list), skipped

    # ------------------------------------------------------------------
    # Prices
    # ------------------------------------------------------------------

    @api.model
    def _to_datetime(self, date):
        if not date:
            return fields.Datetime.now()
        if isinstance(date, datetime):
            return date
        if isinstance(date, date_type):
            return datetime.combine(date, datetime.min.time())
        return fields.Datetime.to_datetime(date)

    @api.model
    def _express_unit_price(self, service_type, garment_unit_price, currency):
        if service_type.express_surcharge_kind == "fixed":
            company_currency = self.env.company.currency_id
            return company_currency._convert(
                service_type.express_surcharge_value,
                currency,
                self.env.company,
                fields.Date.context_today(self),
                round=False,
            )
        return garment_unit_price * service_type.express_surcharge_value / 100.0

    @api.model
    def price_item(
        self,
        product,
        partner,
        branch,
        channel,
        surcharges=None,
        express=False,
        date=None,
        quantity=1,
    ):
        """Price one garment item with its surcharges and express charge.

        :param product: laundry ``product.product``
        :param partner: ``res.partner`` (or empty): a corporate contract price
            list of its commercial partner wins
        :param branch: ``earlydryer.branch`` (or empty)
        :param channel: ``walk_in``, ``pickup`` or ``corporate``
        :param surcharges: ``earlydryer.surcharge`` recordset; fixed ones price
            their own product through the same price list, percent ones apply
            to the garment unit price
        :param express: add the express charge of the product's service type
            (percent of the garment unit price, or a fixed amount)
        :param date: price date (date or datetime, default now); price list
            items are filtered on it
        :param quantity: number of identical items
        :raises UserError: express requested but not available, or a surcharge
            that does not apply to this garment and service
        :returns: dict with plain values::

            {"pricelist_id": int or False,
             "currency_id": int,
             "unit_price": float,
             "surcharge_lines": [{"surcharge_id", "product_id", "unit_price"}],
             "express_line": {"product_id", "unit_price"} or None,
             "total": float}

            ``unit_price`` values are per item; ``total`` is (garment +
            surcharges + express) × ``quantity``. Currency rounding is applied
            at the end.
        """
        product.ensure_one()
        surcharges = surcharges or self.env["earlydryer.surcharge"]
        price_date = self._to_datetime(date)
        pricelist = self.env["product.pricelist"]._earlydryer_resolve_pricelist(
            partner, branch, channel, price_date
        )
        currency = pricelist.currency_id or (
            branch.company_id.currency_id if branch else self.env.company.currency_id
        )
        category = product.earlydryer_garment_category_id
        service_type = product.earlydryer_service_type_id

        fixed = surcharges.filtered(lambda s: s.compute_mode == "fixed")
        prices = pricelist._get_products_price(
            product | fixed.product_id, quantity, currency=currency, date=price_date
        )
        unit_price = prices[product.id]

        surcharge_lines = []
        for surcharge in surcharges:
            if not surcharge._is_applicable(category, service_type):
                raise UserError(
                    self.env._(
                        "Surcharge %(surcharge)s does not apply to %(product)s.",
                        surcharge=surcharge.display_name,
                        product=product.display_name,
                    )
                )
            if surcharge.compute_mode == "fixed":
                surcharge_price = prices[surcharge.product_id.id]
            else:
                surcharge_price = unit_price * surcharge.percent / 100.0
            surcharge_lines.append(
                {
                    "surcharge_id": surcharge.id,
                    "product_id": surcharge.product_id.id,
                    "unit_price": surcharge_price,
                }
            )

        express_line = None
        if express:
            if not service_type.express_available:
                raise UserError(
                    self.env._(
                        "Express is not available for %(service)s.",
                        service=service_type.display_name,
                    )
                )
            express_line = {
                "product_id": self.get_express_product().id,
                "unit_price": self._express_unit_price(
                    service_type, unit_price, currency
                ),
            }

        unit_price = currency.round(unit_price)
        for line in surcharge_lines:
            line["unit_price"] = currency.round(line["unit_price"])
        if express_line:
            express_line["unit_price"] = currency.round(express_line["unit_price"])
        per_item = (
            unit_price
            + sum(line["unit_price"] for line in surcharge_lines)
            + (express_line["unit_price"] if express_line else 0.0)
        )
        return {
            "pricelist_id": pricelist.id or False,
            "currency_id": currency.id,
            "unit_price": unit_price,
            "surcharge_lines": surcharge_lines,
            "express_line": express_line,
            "total": currency.round(per_item * quantity),
        }

    # ------------------------------------------------------------------
    # Turnaround
    # ------------------------------------------------------------------

    @api.model
    def _turnaround_hours_of(self, item, express):
        """Hours of a service type or of a laundry product (with overrides)."""
        if item._name == "earlydryer.service.type":
            return item._turnaround_hours(express)
        if express and item.earlydryer_express_available:
            return item.earlydryer_express_turnaround_hours
        return item.earlydryer_turnaround_hours

    @api.model
    def _add_working_hours(self, branch, start, hours):
        calendar = branch.resource_calendar_id if branch else False
        if calendar:
            end = calendar.plan_hours(hours, start, compute_leaves=True)
            if end:
                return end
            _logger.warning(
                "Calendar %s of branch %s has no working time; turnaround "
                "counted in plain hours.",
                calendar.display_name,
                branch.display_name,
            )
        return start + timedelta(hours=hours)

    @api.model
    def promised_datetime(self, service_types, branch, express=False, start=None):
        """Return the promised ready datetime (naive UTC) of a set of items.

        :param service_types: ``earlydryer.service.type`` recordset, or laundry
            ``product.product`` / ``product.template`` records (then the
            per-product turnaround overrides are used)
        :param branch: ``earlydryer.branch``; its ``resource_calendar_id``
            (operating hours, public holidays included) is used to count the
            turnaround in working hours. Without a calendar, plain hours.
        :param express: use the express turnaround where available (items
            without express keep their standard turnaround)
        :param start: drop-off datetime (naive UTC), default now
        :returns: the latest promise among the items, or ``start`` when no
            item is given
        """
        start = start or fields.Datetime.now()
        hours_set = {self._turnaround_hours_of(item, express) for item in service_types}
        if not hours_set:
            return start
        return max(self._add_working_hours(branch, start, hours) for hours in hours_set)

    # ------------------------------------------------------------------
    # Catalogue for the website / API
    # ------------------------------------------------------------------

    @api.model
    def catalog_for_branch(self, branch, channel, partner=None, date=None):
        """Return the sellable catalogue of a plant and channel as plain data.

        For ``earlydryer_api`` (website). Only JSON-serialisable types::

            [{"id", "code", "name", "group", "piece_count",
              "services": [{"product_id", "default_code", "service_type_id",
                            "code", "name", "price", "currency",
                            "requires_tag", "turnaround_hours",
                            "express_available", "express_turnaround_hours",
                            "express_price",
                            "surcharges": [{"id", "code", "name", "kind",
                                            "compute_mode", "percent",
                                            "price"}]}]}]

        Categories without any sellable service are left out. Prices come
        from the same price list as :meth:`price_item`.
        """
        price_date = self._to_datetime(date)
        pricelist = self.env["product.pricelist"]._earlydryer_resolve_pricelist(
            partner, branch, channel, price_date
        )
        currency = pricelist.currency_id or self.env.company.currency_id
        products = self.env["product.product"].search(
            [
                ("earlydryer_kind", "=", "laundry"),
                ("sale_ok", "=", True),
                ("earlydryer_garment_category_id.active", "=", True),
                ("earlydryer_service_type_id.active", "=", True),
                ("company_id", "in", [self.env.company.id, False]),
            ]
        )
        # a handful of configuration records
        surcharges = self.env["earlydryer.surcharge"].search([])  # pylint: disable=no-search-all
        prices = pricelist._get_products_price(
            products | surcharges.product_id, 1, currency=currency, date=price_date
        )
        result = []
        by_category = products.grouped("earlydryer_garment_category_id")
        for category in sorted(by_category, key=lambda c: (c.sequence, c.name)):
            services = []
            category_products = by_category[category].sorted(
                lambda p: (
                    p.earlydryer_service_type_id.sequence,
                    p.earlydryer_service_type_id.name,
                )
            )
            for product in category_products:
                service = product.earlydryer_service_type_id
                price = prices[product.id]
                express_price = (
                    currency.round(self._express_unit_price(service, price, currency))
                    if service.express_available
                    else None
                )
                services.append(
                    {
                        "product_id": product.id,
                        "default_code": product.default_code or "",
                        "service_type_id": service.id,
                        "code": service.code,
                        "name": service.name,
                        "price": currency.round(price),
                        "currency": currency.name,
                        "requires_tag": service.requires_tag,
                        "turnaround_hours": product.earlydryer_turnaround_hours,
                        "express_available": service.express_available,
                        "express_turnaround_hours": (
                            product.earlydryer_express_turnaround_hours
                            if service.express_available
                            else None
                        ),
                        "express_price": express_price,
                        "surcharges": [
                            {
                                "id": surcharge.id,
                                "code": surcharge.code,
                                "name": surcharge.name,
                                "kind": surcharge.kind,
                                "compute_mode": surcharge.compute_mode,
                                "percent": surcharge.percent
                                if surcharge.compute_mode == "percent"
                                else None,
                                "price": currency.round(
                                    prices[surcharge.product_id.id]
                                    if surcharge.compute_mode == "fixed"
                                    else price * surcharge.percent / 100.0
                                ),
                            }
                            for surcharge in surcharges
                            if surcharge._is_applicable(category, service)
                        ],
                    }
                )
            result.append(
                {
                    "id": category.id,
                    "code": category.code,
                    "name": category.name,
                    "group": category.garment_group,
                    "piece_count": category.piece_count,
                    "services": services,
                }
            )
        return result

    # ------------------------------------------------------------------
    # Demo data
    # ------------------------------------------------------------------

    @api.model
    def _load_demo_catalog(self, walk_in_pricelist_id):
        """Demo only: generate the catalogue and fixed walk-in prices.

        Placeholder Naira prices: a base price per garment category times a
        factor per service type, rounded to ₦50. Real prices replace them.
        """
        Category = self.env["earlydryer.garment.category"]
        categories = Category.search([])  # pylint: disable=no-search-all
        services = self.env["earlydryer.service.type"].search([])  # pylint: disable=no-search-all
        templates, _skipped = self._generate_laundry_products(categories, services)
        base = {
            "SHIRT": 800, "TROUS": 800, "AGBAD": 3500, "SENAT": 2000,
            "GOWN": 2500, "SUIT": 3000, "JEANS": 900, "TOWEL": 500,
            "BEDSH": 1000, "DUVET": 5000, "SHOE": 2000, "TBOX": 4000,
            "KAFTN": 1800, "SUIT3": 4000, "JACKT": 2000, "SKIRT": 800,
            "BLOUS": 800, "TIE": 500, "CURTN": 3000, "RUG": 8000, "BAG": 3000,
        }  # fmt: skip
        factor = {
            "WF": 0.7, "WI": 1.0, "DC": 1.5, "IO": 0.5, "ST": 0.8,
            "DCC": 1.0, "RUGC": 1.0, "SHOEC": 1.0, "BAGC": 1.0, "ALT": 1.2,
        }  # fmt: skip
        items = []
        for template in templates:
            price = base.get(
                template.earlydryer_garment_category_id.code, 1000
            ) * factor.get(template.earlydryer_service_type_id.code, 1.0)
            price = max(round(price / 50.0) * 50, 50)
            template.list_price = price
            items.append(
                {
                    "pricelist_id": walk_in_pricelist_id,
                    "applied_on": "1_product",
                    "product_tmpl_id": template.id,
                    "compute_price": "fixed",
                    "fixed_price": price,
                }
            )
        self.env["product.pricelist.item"].create(items)
        return True
