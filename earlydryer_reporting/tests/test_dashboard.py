# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import fields
from odoo.tests import HttpCase, tagged
from odoo.tests.common import new_test_user


@tagged("post_install", "-at_install")
class TestDashboard(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(
            cls.env, login="report_dashboard", groups="earlydryer_base.group_management"
        )

        # Keep the browser checks populated even in a no-demo database. This
        # exercises split values and staff-row template expressions as well.
        partner = cls.env["res.partner"].create({"name": "Browser reporting customer"})
        for number in (1, 2):
            branch = cls.env["earlydryer.branch"].create(
                {"name": f"Browser Plant {number}", "code": f"RB{number}"}
            )
            job = cls.env["laundry.job"].create(
                {"partner_id": partner.id, "earlydryer_branch_id": branch.id}
            )
            cls.env["laundry.job.stage.log"].create(
                {
                    "job_id": job.id,
                    "from_state": "washed",
                    "to_state": "dried",
                    "date": fields.Datetime.now(),
                }
            )

    def test_dashboard_tile_tour(self):
        action = self.env.ref("earlydryer_reporting.action_dashboard")
        self.start_tour(
            f"/odoo/action-{action.id}",
            "earlydryer_reporting_dashboard",
            login="report_dashboard",
        )

    def test_phone_layout_and_filters(self):
        self.browser_size = "375,812"
        action = self.env.ref("earlydryer_reporting.action_dashboard")
        self.browser_js(
            f"/odoo/action-{action.id}",
            """
            const dashboard = document.querySelector('.er-dashboard');
            if (dashboard.scrollWidth > dashboard.clientWidth + 1) throw new Error('Dashboard overflows at phone width');
            const grid = getComputedStyle(document.querySelector('.er-grid')).gridTemplateColumns;
            if (grid.split(' ').length !== 1) throw new Error('Expected one phone column');
            const compare = document.querySelector('.er-compare');
            compare.value = 'year'; compare.dispatchEvent(new Event('change', {bubbles: true}));
            console.log('test successful');
        """,
            ready="!!document.querySelector('.er-dashboard [data-kpi=orders_count]')",
            login="report_dashboard",
        )
