# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.tests import TransactionCase, new_test_user


class EarlydryerCommon(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.company = cls.env.company
        cls.Branch = cls.env["earlydryer.branch"]
        cls.Shelf = cls.env["earlydryer.branch.shelf"]
        cls.branch_1 = cls.Branch.create({"name": "Test Plant 1", "code": "tp1"})
        cls.branch_2 = cls.Branch.create({"name": "Test Plant 2", "code": "TP2"})
        cls.branch_1._generate_shelves("A", 1, 3, 2)
        cls.branch_2._generate_shelves("B", 1, 2, 2)

    @classmethod
    def _new_user(cls, login, groups, branches=None):
        branches = branches or cls.Branch
        return new_test_user(
            cls.env,
            login=login,
            groups=groups,
            earlydryer_branch_ids=[(6, 0, branches.ids)],
            earlydryer_branch_id=branches[:1].id,
        )
