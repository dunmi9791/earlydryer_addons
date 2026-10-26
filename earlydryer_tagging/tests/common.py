# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.tests import tagged

from odoo.addons.earlydryer_laundry_order.tests.common import LaundryJobCommon


@tagged("post_install", "-at_install")
class TaggingCommon(LaundryJobCommon):
    """Laundry job test data; plant 1 printed tags, plant 2 pre-printed."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.TagCode = cls.env["earlydryer.tag.code"]
        cls.Range = cls.env["earlydryer.tag.range"]
        cls.ScanLog = cls.env["earlydryer.scan.log"]
        cls.History = cls.env["earlydryer.tag.history"]
        # LaundryJobCommon turns the packing scan off for the earlier tests
        cls.branch_1.tag_require_packing_scan = True
        cls.branch_2.write(
            {
                "tag_mode": "preprinted",
                "tag_preprinted_pattern": r"^TT[0-9]{4}$",
                "tag_require_packing_scan": True,
            }
        )
        cls.branch_1.manager_id = cls.user_manager
        cls.user_production = cls._new_user(
            "t_production", "earlydryer_base.group_production", cls.branch_1
        )
        cls.user_rider = cls._new_user(
            "t_rider", "earlydryer_base.group_rider", cls.branch_1
        )
        cls.user_manager_2 = cls._new_user(
            "t_manager_2", "earlydryer_base.group_branch_manager", cls.branch_2
        )

    @classmethod
    def _job_qc_passed(cls, lines=None, branch=None):
        """A job at QC with every item passed (ready to pack)."""
        job = cls._create_job(lines, branch)
        employee = (
            cls.employee if (branch or cls.branch_1) == cls.branch_1 else cls.employee_2
        )
        if job.tag_mode == "preprinted":
            for number, item in enumerate(
                job.item_ids._earlydryer_needs_tag(), start=1
            ):
                item.tag_code = f"TT{job.id % 100:02d}{number:02d}"
        for state in cls.PRODUCTION_PATH:
            job.action_move_to(state, employee=employee)
        job.action_qc_pass(employee=employee)
        return job
