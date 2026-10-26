# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from datetime import timedelta
from itertools import count

from odoo import fields
from odoo.fields import Command

from odoo.addons.earlydryer_tagging.tests.common import TaggingCommon

_uid = count(1)


class EarlydryerPosCommon(TaggingCommon):
    """A laundry counter on test plant 1 (printed tags) and one on plant 2
    (pre-printed tags), with cash and Customer Account methods."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        company = cls.env.company
        if not company.chart_template:
            cls.env["account.chart.template"].try_loading(
                "generic_coa", company=company, install_demo=False
            )
        cls.Order = cls.env["pos.order"]
        cls.Collection = cls.env["earlydryer.pos.collection"]
        cls.Request = cls.env["earlydryer.approval.request"]
        cls.product_settlement = cls.env.ref("earlydryer_pos.product_settlement")
        cls.express = cls.Catalog.get_express_product()
        # suit: 2 pieces (laundry_order test data); beads: fixed surcharge
        cls.Item.create(
            cls._fixed_item(cls.suit_dc, 3000, pricelist_id=cls.pl_walk_in_b1.id)
        )
        cls.walk_in = cls.env["res.partner"].create({"name": "T Walk-in"})
        cls.journal_cash = cls.env["account.journal"].create(
            {"name": "T POS Cash", "type": "cash", "code": "TPCS"}
        )
        cls.journal_cash_2 = cls.env["account.journal"].create(
            {"name": "T POS Cash 2", "type": "cash", "code": "TPC2"}
        )
        cls.pm_cash = cls.env["pos.payment.method"].create(
            {"name": "T Cash", "journal_id": cls.journal_cash.id}
        )
        cls.pm_cash_2 = cls.env["pos.payment.method"].create(
            {"name": "T Cash 2", "journal_id": cls.journal_cash_2.id}
        )
        cls.pm_account = cls.env["pos.payment.method"].create(
            {"name": "T Customer Account", "split_transactions": True}
        )
        cls.config = cls._new_config(
            "T Counter 1", cls.branch_1, cls.pl_walk_in_b1, cls.pm_cash
        )
        cls.config_2 = cls._new_config(
            "T Counter 2", cls.branch_2, cls.pl_walk_in_b2, cls.pm_cash_2
        )
        cls.config._earlydryer_top_up_tag_ranges()

        Employee = cls.env["hr.employee"]
        cls.emp_front_desk = Employee.create(
            {
                "name": "T Front Desk",
                "user_id": cls.user_front_desk.id,
                "earlydryer_branch_id": cls.branch_1.id,
                "pin": "1234",
            }
        )
        cls.emp_manager = Employee.create(
            {
                "name": "T Manager",
                "user_id": cls.user_manager.id,
                "earlydryer_branch_id": cls.branch_1.id,
                "pin": "9876",
            }
        )
        Rule = cls.env["earlydryer.approval.rule"]
        cls.rule_discount_fd = Rule.create(
            {
                "name": "T till discount up to 5%",
                "sequence": 1,
                "approval_type": "discount",
                "model_id": cls.env.ref("point_of_sale.model_pos_order").id,
                "threshold_kind": "percent",
                "min_value": 0,
                "max_value": 5,
                "branch_ids": [Command.set((cls.branch_1 | cls.branch_2).ids)],
                "approver_group_id": cls.env.ref("earlydryer_base.group_front_desk").id,
                "self_approve": True,
            }
        )
        cls.rule_discount_bm = Rule.create(
            {
                "name": "T till discount above 5%",
                "sequence": 2,
                "approval_type": "discount",
                "model_id": cls.env.ref("point_of_sale.model_pos_order").id,
                "threshold_kind": "percent",
                "min_value": 5,
                "max_value": 0,
                "branch_ids": [Command.set((cls.branch_1 | cls.branch_2).ids)],
                "approver_group_id": cls.env.ref(
                    "earlydryer_base.group_branch_manager"
                ).id,
            }
        )

    @classmethod
    def _new_config(cls, name, branch, pricelist, cash_method):
        config = cls.env["pos.config"].create(
            {
                "name": name,
                "earlydryer_branch_id": branch.id,
                "use_pricelist": True,
                "pricelist_id": pricelist.id,
                "available_pricelist_ids": [Command.set(pricelist.ids)],
                "payment_method_ids": [
                    Command.set([cash_method.id, cls.pm_account.id])
                ],
                "module_pos_hr": True,
            }
        )
        config.write(
            {"earlydryer_enabled": True, "earlydryer_walkin_partner_id": cls.walk_in.id}
        )
        return config

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _open_session(self, config=None):
        config = config or self.config
        if not config.current_session_id:
            config.open_ui()
            config.current_session_id.set_opening_control(0, None)
        return config.current_session_id

    def _close_session(self, session):
        cash = sum(
            session.order_ids.payment_ids.filtered(
                lambda p: p.payment_method_id.is_cash_count
            ).mapped("amount")
        )
        session.post_closing_cash_details(cash)
        res = session.close_session_from_ui()
        self.assertTrue(res.get("successful", True), res)
        self.assertEqual(session.state, "closed")

    def _price(self, product, config=None):
        return (config or self.config).pricelist_id._get_product_price(product, 1)

    def _line(self, product, qty=1, price=None, uuid=None, **extra):
        price = self._price(product) if price is None else price
        discount = extra.get("discount", 0.0)
        subtotal = price * qty * (1 - discount / 100.0)
        return (
            0,
            0,
            {
                "uuid": uuid or f"t-line-{next(_uid)}",
                "product_id": product.id,
                "qty": qty,
                "price_unit": price,
                "price_subtotal": subtotal,
                "price_subtotal_incl": subtotal,
                "tax_ids": [(6, 0, [])],
                "discount": 0.0,
                **extra,
            },
        )

    def _payload(
        self,
        lines,
        partner=None,
        paid=None,
        account=0.0,
        config=None,
        uuid=None,
        **extra,
    ):
        """A synced order as the till sends it: ``paid`` in cash (default
        everything but ``account``), ``account`` on Customer Account."""
        config = config or self.config
        session = self._open_session(config)
        total = sum(line[2]["price_subtotal_incl"] for line in lines)
        cash_method = config.payment_method_ids.filtered("is_cash_count")[:1]
        paid = total - account if paid is None else paid
        payments = []
        if paid:
            payments.append(
                (0, 0, {"amount": paid, "payment_method_id": cash_method.id})
            )
        if account:
            payments.append(
                (0, 0, {"amount": account, "payment_method_id": self.pm_account.id})
            )
        return {
            "uuid": uuid or f"t-order-{next(_uid)}",
            "name": "T Order",
            "session_id": session.id,
            "partner_id": (partner or self.partner).id
            if partner is not False
            else False,
            "pricelist_id": config.pricelist_id.id,
            "user_id": self.env.uid,
            "employee_id": self.emp_front_desk.id,
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
            **extra,
        }

    def _sync(self, payload, env=None):
        env = env or self.env
        result = env["pos.order"].sync_from_ui([payload])
        return env["pos.order"].browse(result["pos.order"][0]["id"])

    def _codes(self, count_):
        """Codes the till would print from its range."""
        tag_range = self.env["earlydryer.tag.range"].search(
            [("pos_config_id", "=", self.config.id), ("state", "=", "active")], limit=1
        )
        first = tag_range.next_number
        return [
            self.TagCode.format_number(self.branch_1, first + i) for i in range(count_)
        ]

    def _make_ready(self, job):
        shelf = job.earlydryer_branch_id.shelf_ids[:1]
        job.sudo().with_context(earlydryer_stage_move=True).write(
            {"state": "ready", "shelf_id": shelf.id, "ready_on": fields.Datetime.now()}
        )
        return job

    @staticmethod
    def _hours_ago(hours):
        return fields.Datetime.to_string(fields.Datetime.now() - timedelta(hours=hours))
