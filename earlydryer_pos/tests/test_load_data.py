# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.tests import tagged

from .common import EarlydryerPosCommon


@tagged("post_install", "-at_install")
class TestLoadData(EarlydryerPosCommon):
    def test_session_data(self):
        self.branch_1.resource_calendar_id = self.env.ref(
            "resource.resource_calendar_std"
        )
        session = self._open_session()
        session = session.with_user(self.user_front_desk)
        params = session.load_data_params()
        self.assertIn("earlydryer_tag_codes", params["pos.order.line"]["fields"])
        self.assertIn("earlydryer_parent_line_uuid", params["pos.order.line"]["fields"])
        self.assertIn(
            "earlydryer_discount_approver_employee_id",
            params["pos.order.line"]["fields"],
        )
        self.assertIn("earlydryer_kind", params["product.template"]["fields"])
        data = session.load_data([])
        for model in (
            "earlydryer.garment.category",
            "earlydryer.service.type",
            "earlydryer.surcharge",
            "earlydryer.approval.rule",
        ):
            self.assertIn(model, data)
        self.assertIn(
            self.cat_suit.id, [c["id"] for c in data["earlydryer.garment.category"]]
        )
        rule_ids = [r["id"] for r in data["earlydryer.approval.rule"]]
        self.assertIn(self.rule_discount_bm.id, rule_ids)
        self.assertNotIn("approver_group_id", data["earlydryer.approval.rule"][0])
        employees = {e["id"]: e for e in data["hr.employee"]}
        manager = employees[self.emp_manager.id]
        self.assertIn(self.rule_discount_bm.id, manager["_earlydryer_rule_ids"])
        self.assertNotEqual(manager.get("_pin"), "9876")  # hashed by pos_hr
        config = data["pos.config"][0]
        self.assertTrue(config["earlydryer_enabled"])
        payload = config["_earlydryer"]
        self.assertTrue(payload["ranges"])
        self.assertEqual(payload["branch"]["tag_prefix"], self.branch_1.tag_prefix)
        self.assertIn("jobs", payload["collection"])
        self.assertEqual(payload["account_method_ids"], [self.pm_account.id])
        calendar = payload["calendar"]
        self.assertTrue(calendar["attendances"])
        self.assertTrue(
            all(a["hour_to"] > a["hour_from"] for a in calendar["attendances"])
        )

    def test_collection_cache_cap(self):
        jobs = self.Job.browse()
        for _i in range(3):
            line = self._line(self.shirt_wi, earlydryer_tag_codes=self._codes(1)[0])
            order = self._sync(self._payload([line]))
            jobs |= self._make_ready(order.earlydryer_job_id)
        cache = self.Job._earlydryer_pos_collection_cache(self.branch_1, 30, limit=2)
        self.assertEqual(len(cache["jobs"]), 2)
        self.assertTrue(cache["capped"])
        cache = self.Job._earlydryer_pos_collection_cache(self.branch_1, 30)
        self.assertFalse(cache["capped"])
        card = next(job for job in cache["jobs"] if job["id"] == jobs[0].id)
        self.assertEqual(card["shelf"], jobs[0].shelf_id.name)
        self.assertEqual(card["amount_due"], 0)
        self.assertTrue(card["tags"])

    def test_refresh_tops_up_ranges(self):
        self._open_session()
        ranges = self.env["earlydryer.tag.range"].search(
            [("pos_config_id", "=", self.config.id)]
        )
        ranges.write({"next_number": ranges[0].end_number - 5})
        payload = self.config.with_user(self.user_front_desk).earlydryer_pos_refresh()
        self.assertEqual(len(payload["ranges"]), 2)
