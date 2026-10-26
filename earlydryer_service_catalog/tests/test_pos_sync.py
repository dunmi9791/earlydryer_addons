# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import CatalogCommon


@tagged("post_install", "-at_install")
class TestPosSync(CatalogCommon):
    def test_sync_pos_pricelists(self):
        contract_all = self.Pricelist.create(
            {"name": "T Contract all", "earlydryer_channel": "corporate",
             "earlydryer_is_contract": True}
        )  # fmt: skip
        contract_b2 = self.Pricelist.create(
            {"name": "T Contract B2", "earlydryer_channel": "corporate",
             "earlydryer_is_contract": True, "earlydryer_branch_id": self.branch_2.id}
        )  # fmt: skip
        with self.assertRaises(UserError):
            self.branch_1.action_earlydryer_sync_pos_pricelists()
        config = self.env["pos.config"].create(
            {"name": "T Counter", "earlydryer_branch_id": self.branch_1.id}
        )
        self.branch_1.action_earlydryer_sync_pos_pricelists()
        self.assertTrue(config.use_pricelist)
        self.assertEqual(config.pricelist_id, self.pl_walk_in_b1)
        self.assertIn(contract_all, config.available_pricelist_ids)
        self.assertIn(self.pl_walk_in_b1, config.available_pricelist_ids)
        self.assertNotIn(contract_b2, config.available_pricelist_ids)
        # loaded by the POS session (offline): price list and its items
        self.assertIn(self.pl_walk_in_b1, config._get_available_pricelists())
