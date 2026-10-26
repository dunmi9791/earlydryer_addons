# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.addons.earlydryer_service_catalog.tests.common import CatalogCommon
from odoo.fields import Command


class LaundryJobCommon(CatalogCommon):
    """Catalogue test data plus users, employees and helpers for jobs."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Job = cls.env["laundry.job"]
        cls.Log = cls.env["laundry.job.stage.log"]
        cls.Employee = cls.env["hr.employee"]
        # earlydryer_tagging (when installed) requires every garment to be
        # scanned at packing; these tests pack without scanning
        if "tag_require_packing_scan" in cls.Branch._fields:
            (cls.branch_1 | cls.branch_2).tag_require_packing_scan = False
        # earlydryer_production (when installed) requires a colour group per
        # garment before Sorted and a reason for each QC failure; these tests
        # move jobs without sorting them and fail QC with a note only
        if "require_sorting_colour_group" in cls.Branch._fields:
            (cls.branch_1 | cls.branch_2).write(
                {"require_sorting_colour_group": False, "qc_reason_required": False}
            )

        cls.cat_suit = cls.Category.create(
            {
                "name": "T Suit",
                "code": "TSUIT",
                "garment_group": "suits_outerwear",
                "piece_count": 2,
            }
        )
        cls.svc_io = cls.Service.create(
            {
                "name": "T Ironing Only",
                "code": "TIO",
                "standard_turnaround_hours": 8,
                "uses_wash": False,
                "uses_dry": False,
            }
        )
        cls.Catalog._generate_laundry_products(
            cls.cat_suit | cls.cat_shirt, cls.svc_dc | cls.svc_io
        )
        cls.suit_dc = cls.Catalog.get_laundry_product(cls.cat_suit, cls.svc_dc)
        cls.shirt_io = cls.Catalog.get_laundry_product(cls.cat_shirt, cls.svc_io)
        (cls.suit_dc | cls.shirt_io).list_price = 100
        # one price list per plant and channel used here (no fallback warning)
        cls.pl_walk_in_b2 = cls.Pricelist.create(
            {
                "name": "T Walk-in B2",
                "earlydryer_channel": "walk_in",
                "earlydryer_branch_id": cls.branch_2.id,
            }
        )
        cls.pl_pickup = cls.Pricelist.create(
            {"name": "T Pickup", "earlydryer_channel": "pickup"}
        )

        cls.partner = cls.env["res.partner"].create(
            {"name": "T Customer", "phone": "+234 800 555 0101"}
        )
        cls.user_front_desk = cls._new_user(
            "t_front_desk", "earlydryer_base.group_front_desk", cls.branch_1
        )
        cls.user_front_desk_2 = cls._new_user(
            "t_front_desk_2", "earlydryer_base.group_front_desk", cls.branch_2
        )
        cls.user_qc = cls._new_user("t_qc", "earlydryer_base.group_qc", cls.branch_1)
        cls.user_manager = cls._new_user(
            "t_manager", "earlydryer_base.group_branch_manager", cls.branch_1
        )
        cls.user_finance = cls._new_user("t_finance", "earlydryer_base.group_finance")
        cls.employee = cls.Employee.create(
            {"name": "T Washer", "earlydryer_branch_id": cls.branch_1.id}
        )
        cls.employee_2 = cls.Employee.create(
            {"name": "T Washer 2", "earlydryer_branch_id": cls.branch_2.id}
        )

    @classmethod
    def _create_sale(
        cls,
        lines,
        branch=None,
        channel="walk_in",
        fulfilment="collect",
        express=False,
        partner=None,
    ):
        """``lines``: list of (product, quantity, surcharges)."""
        return cls.env["sale.order"].create(
            {
                "partner_id": (partner or cls.partner).id,
                "earlydryer_branch_id": (branch or cls.branch_1).id,
                "earlydryer_channel": channel,
                "earlydryer_fulfilment": fulfilment,
                "earlydryer_express": express,
                "order_line": [
                    Command.create(
                        {
                            "product_id": product.id,
                            "product_uom_qty": quantity,
                            "earlydryer_surcharge_ids": [
                                Command.set(surcharges.ids if surcharges else [])
                            ],
                        }
                    )
                    for product, quantity, surcharges in lines
                ],
            }
        )

    @classmethod
    def _create_job(cls, lines=None, branch=None, **kwargs):
        """A job from a confirmed sales order (one shirt by default)."""
        sale = cls._create_sale(lines or [(cls.shirt_wi, 1, None)], branch, **kwargs)
        sale.action_confirm()
        return sale.laundry_job_ids

    def _walk(self, job, states, employee=None):
        employee = employee or self.employee
        for state in states:
            if state == "qc_pass":
                job.action_qc_pass(employee=employee)
            else:
                job.action_move_to(state, employee=employee)

    PRODUCTION_PATH = ["tagged", "sorted", "washed", "dried", "ironed", "qc"]

    def _last_log(self, job):
        return self.Log.search([("job_id", "=", job.id)], limit=1)
