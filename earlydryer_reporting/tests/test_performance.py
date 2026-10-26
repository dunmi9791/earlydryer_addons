# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import logging
import os
import time
import unittest
from unittest.mock import patch

from odoo.tests import tagged
from odoo.tools import SQL

from .common import ReportingCommon


@tagged("post_install", "-at_install")
@unittest.skipUnless(
    os.environ.get("EARLYDRYER_PERF_TEST") == "1",
    "Set EARLYDRYER_PERF_TEST=1 for 50,000-job benchmark",
)
class TestPerformance(ReportingCommon):
    def test_full_dashboard_50000_jobs(self):
        # SQL fixture only: no 50,000 operational workflows or notification jobs.
        self.env.cr.execute(
            SQL(
                """INSERT INTO laundry_job(name,earlydryer_branch_id,company_id,partner_id,state,channel,fulfilment,received_on,promised_on,ready_on,closed_on,express,item_count)
        SELECT 'PERF/'||n,CASE WHEN n%%2=0 THEN %s ELSE %s END,%s,%s,'collected','walk_in','collect',
        timestamp '2026-10-01'+(n%%28)*interval '1 day',timestamp '2026-10-03'+(n%%28)*interval '1 day',timestamp '2026-10-02'+(n%%28)*interval '1 day',timestamp '2026-10-03'+(n%%28)*interval '1 day',false,1
        FROM generate_series(1,50000) n""",
                self.branch_1.id,
                self.branch_2.id,
                self.env.company.id,
                self.partner.id,
            )
        )
        self.env.cr.execute(
            SQL(
                """INSERT INTO laundry_job_item(job_id,earlydryer_branch_id,company_id,job_state,product_id,garment_category_id,service_type_id,piece_index,piece_count,price_unit,qc_state,rework_count,missing)
            SELECT id,earlydryer_branch_id,company_id,state,%s,%s,%s,1,1,100,'passed',0,false
            FROM laundry_job WHERE name LIKE 'PERF/%%' AND earlydryer_branch_id=ANY(%s)""",
                self.shirt_wi.id,
                self.shirt_wi.earlydryer_garment_category_id.id,
                self.shirt_wi.earlydryer_service_type_id.id,
                (self.branch_1 | self.branch_2).ids,
            )
        )
        self.env.cr.execute(
            SQL(
                """INSERT INTO laundry_job_stage_log(job_id,earlydryer_branch_id,company_id,from_state,to_state,date,employee_id,user_id,duration_hours)
            SELECT id,earlydryer_branch_id,company_id,'washed','ready',ready_on,%s,%s,24 FROM laundry_job WHERE name LIKE 'PERF/%%' AND earlydryer_branch_id=ANY(%s)""",
                self.employee.id,
                self.env.uid,
                (self.branch_1 | self.branch_2).ids,
            )
        )
        if "item_count" in self.env["laundry.job.stage.log"]._fields:
            self.env.cr.execute(
                SQL(
                    "UPDATE laundry_job_stage_log SET item_count=1,source='system' WHERE job_id IN (SELECT id FROM laundry_job WHERE name LIKE 'PERF/%%' AND earlydryer_branch_id=ANY(%s))",
                    (self.branch_1 | self.branch_2).ids,
                )
            )
        for table in ("laundry_job", "laundry_job_item", "laundry_job_stage_log"):
            self.env.cr.execute(SQL("ANALYZE %s", SQL.identifier(table)))
        timings = []
        original = type(self.Kpi)._query

        def timed(service, cache, key, query):
            began = time.monotonic()
            rows = original(service, cache, key, query)
            timings.append((str(key[0]), time.monotonic() - began))
            return rows

        start = time.monotonic()
        with patch.object(type(self.Kpi), "_query", timed):
            data = self.Kpi.compute(
                [], (self.branch_1 | self.branch_2).ids, "2026-10-01", "2026-10-31"
            )
        elapsed = time.monotonic() - start
        self.assertEqual(data["orders_count"]["value"], 50000)
        self.assertEqual(data["items_count"]["value"], 50000)
        logging.getLogger(__name__).info("EARLYDRYER_PERF timings %s", timings)
        self.assertLess(elapsed, 1.0, f"Full dashboard: {elapsed:.3f}s for 50,000 jobs")
        logging.getLogger(__name__).info("EARLYDRYER_PERF 50000 jobs %.3fs", elapsed)
