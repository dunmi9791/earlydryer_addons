# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from odoo.addons.bus.models.ir_websocket import IrWebsocket as BusIrWebsocket

from .common import ProductionCommon


@tagged("post_install", "-at_install")
class TestBoard(ProductionCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = fields.Datetime.now()
        cls.job_plain = cls._job_in("tagged")
        cls.job_express = cls._job_in("tagged", express=True)
        cls.job_overdue = cls._job_in("tagged")
        cls.job_late_express = cls._job_in("tagged", express=True)
        (cls.job_overdue | cls.job_late_express).promised_on = now - timedelta(hours=2)
        cls.job_plain.promised_on = now + timedelta(hours=1)
        cls.job_express.promised_on = now + timedelta(hours=5)
        cls.job_other_plant = cls._job_in("tagged", branch=cls.branch_2)

    def _cards(self, data, state):
        column = next(c for c in data["columns"] if c["state"] == state)
        return [card["id"] for card in column["cards"]]

    def test_board_shows_only_own_branch(self):
        Job = self.Job.with_user(self.user_front_desk)
        data = Job.earlydryer_board_data(self.branch_2.id)
        # not allowed on plant 2: falls back to the user's plant
        self.assertEqual(data["branch"]["id"], self.branch_1.id)
        ids = [card["id"] for col in data["columns"] for card in col["cards"]]
        self.assertNotIn(self.job_other_plant.id, ids)
        self.assertIn(self.job_plain.id, ids)
        self.assertFalse(data["branches"])
        self.assertNotIn("out_for_delivery", [c["state"] for c in data["columns"]])

    def test_board_sort_order(self):
        data = self.Job.with_user(self.user_front_desk)._earlydryer_board_data(
            self.branch_1.id
        )
        tagged = self._cards(data, "tagged")
        expected = [
            self.job_late_express.id,
            self.job_overdue.id,
            self.job_express.id,
            self.job_plain.id,
        ]
        self.assertEqual([i for i in tagged if i in expected], expected)

    def test_board_filters(self):
        Job = self.Job.with_user(self.user_front_desk)
        data = Job.earlydryer_board_data(self.branch_1.id, {"express": True})
        tagged = self._cards(data, "tagged")
        self.assertIn(self.job_express.id, tagged)
        self.assertNotIn(self.job_plain.id, tagged)
        data = Job.earlydryer_board_data(self.branch_1.id, {"overdue": True})
        self.assertEqual(
            set(self._cards(data, "tagged")),
            {self.job_overdue.id, self.job_late_express.id},
        )
        data = Job.earlydryer_board_data(
            self.branch_1.id, {"search": self.job_plain.name}
        )
        self.assertEqual(self._cards(data, "tagged"), [self.job_plain.id])
        tag = self.job_express.item_ids[:1].tag_code
        data = Job.earlydryer_board_data(self.branch_1.id, {"search": tag})
        self.assertEqual(self._cards(data, "tagged"), [self.job_express.id])
        data = Job.earlydryer_board_data(self.branch_1.id, {"channel": "pickup"})
        self.assertFalse(self._cards(data, "tagged"))

    def test_board_card(self):
        card = self.job_overdue._earlydryer_board_card()
        self.assertTrue(card["overdue"])
        self.assertEqual(card["next_state"], "sorted")
        self.assertEqual(card["item_count"], 1)
        self.assertTrue(card["balance_due"])
        res = self.Job.with_user(self.user_front_desk).earlydryer_board_cards(
            [self.job_plain.id, self.job_other_plant.id]
        )
        self.assertEqual([c["id"] for c in res["cards"]], [self.job_plain.id])
        self.assertEqual(res["removed_ids"], [self.job_other_plant.id])

    def test_board_move_uses_action_move_to(self):
        Job = self.Job.with_user(self.user_front_desk)
        # production stage without employee: refused, stage unchanged
        res = Job.earlydryer_board_move([self.job_plain.id], "sorted")
        self.assertFalse(res["results"][0]["ok"])
        self.assertIn("who did the work", res["results"][0]["message"])
        self.assertEqual(self.job_plain.state, "tagged")
        with patch.object(
            type(self.Job),
            "action_move_to",
            autospec=True,
            side_effect=type(self.Job).action_move_to,
        ) as move:
            res = Job.earlydryer_board_move(
                [self.job_plain.id], "sorted", self.employee.id
            )
        self.assertTrue(move.called)
        self.assertTrue(res["results"][0]["ok"])
        self.assertEqual(self.job_plain.state, "sorted")
        self.assertEqual(res["cards"][0]["state"], "sorted")
        log = self._last_log(self.job_plain)
        self.assertEqual(log.source, "board")
        self.assertEqual(log.employee_id, self.employee)
        self.assertEqual(log.item_count, 1)

    def test_board_move_gates(self):
        job = self._job_in("qc")
        job.action_qc_pass(employee=self.employee)
        job.action_move_to("packed", employee=self.employee)
        res = self.Job.with_user(self.user_front_desk).earlydryer_board_move(
            [job.id], "ready"
        )
        self.assertFalse(res["results"][0]["ok"])
        self.assertIn("shelf", res["results"][0]["message"])
        self.assertEqual(job.state, "packed")

    def test_move_sends_bus_notification(self):
        sent = []
        Bus = type(self.env["bus.bus"])
        original = Bus._sendone

        def sendone(bus, target, notification_type, message):
            sent.append((target, notification_type, message))
            return original(bus, target, notification_type, message)

        with patch.object(Bus, "_sendone", sendone):
            self.job_plain.with_user(self.user_front_desk).action_move_to(
                "sorted", employee=self.employee
            )
        board = [s for s in sent if s[1] == "earlydryer.board/updated"]
        self.assertEqual(len(board), 1)
        target, _type, message = board[0]
        self.assertEqual(target, (self.branch_1, "earlydryer_board"))
        self.assertEqual(message["job_ids"], [self.job_plain.id])

    def test_websocket_channel_needs_branch_access(self):
        # the core part needs an HTTP request: keep only this module's part
        with patch.object(
            BusIrWebsocket, "_build_bus_channel_list", lambda self, channels: channels
        ):
            channels = (
                self.env["ir.websocket"]
                .with_user(self.user_front_desk)
                ._build_bus_channel_list(
                    [
                        f"earlydryer_board_{self.branch_1.id}",
                        f"earlydryer_board_{self.branch_2.id}",
                    ]
                )
            )
        board = [
            c for c in channels if isinstance(c, tuple) and c[1] == "earlydryer_board"
        ]
        self.assertEqual(board, [(self.branch_1, "earlydryer_board")])

    def test_tablet_board_move(self):
        Job = self.Job.with_user(self.user_production)
        identity = Job.earlydryer_tablet_identify("TBADGE-1", self.branch_1.id)
        self.assertTrue(identity["ok"])
        res = Job.earlydryer_board_move(
            [self.job_plain.id], "sorted", tablet_token=identity["token"]
        )
        self.assertTrue(res["results"][0]["ok"])
        log = self._last_log(self.job_plain)
        self.assertEqual((log.source, log.employee_id), ("tablet", self.employee))
        self.assertEqual(log.user_id, self.user_production)
        with self.assertRaises(UserError):
            Job.earlydryer_board_move([self.job_express.id], "sorted", tablet_token="x")

    def test_tablet_scan_moves_garment(self):
        Job = self.Job.with_user(self.user_production)
        res = Job.earlydryer_tablet_scan("TBADGE-1", self.branch_1.id, "sorted", False)
        self.assertEqual(res["kind"], "identity")
        tag = self.job_plain.item_ids.tag_code
        res = Job.earlydryer_tablet_scan(tag, self.branch_1.id, "sorted", res["token"])
        self.assertEqual(res["kind"], "move")
        self.assertEqual(res["results"][0]["result"], "ok")
        self.assertEqual(self.job_plain.state, "sorted")
        self.assertEqual(self._last_log(self.job_plain).source, "tablet")
        # no identification: refused
        res = Job.earlydryer_tablet_scan(
            self.job_express.item_ids.tag_code, self.branch_1.id, "sorted", False
        )
        self.assertEqual(res["kind"], "error")
        self.assertEqual(self.job_express.state, "tagged")

    def test_scan_screen_source(self):
        tag = self.job_plain.item_ids.tag_code
        self.Job.with_user(self.user_production).earlydryer_scan_move(
            [tag], "sorted", self.employee.id
        )
        self.assertEqual(self._last_log(self.job_plain).source, "scan")

    def test_rider_board_read_only(self):
        data = self.Job.with_user(self.user_rider).earlydryer_board_data(
            self.branch_1.id
        )
        self.assertFalse(data["rights"]["move"])
        with self.assertRaises(AccessError):
            self.job_plain.with_user(self.user_rider).action_move_to(
                "sorted", employee=self.employee
            )
