# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields, models


class AccountMove(models.Model):
    _inherit = "account.move"

    earlydryer_logistics_stop_id = fields.Many2one(
        "earlydryer.logistics.stop",
        string="Logistics Stop",
        readonly=True,
        copy=False,
        index="btree_not_null",
    )
    earlydryer_logistics_job_id = fields.Many2one(
        "laundry.job",
        string="Fee of Job",
        readonly=True,
        copy=False,
        index="btree_not_null",
        help="Delivery fee invoice counted in the job's amount due.",
    )
    earlydryer_logistics_trip_id = fields.Many2one(
        "earlydryer.logistics.trip",
        string="Logistics Trip",
        readonly=True,
        copy=False,
        index="btree_not_null",
    )


class AccountPayment(models.Model):
    _inherit = "account.payment"

    earlydryer_logistics_stop_id = fields.Many2one(
        "earlydryer.logistics.stop",
        string="Collected on Stop",
        readonly=True,
        copy=False,
        index="btree_not_null",
    )
