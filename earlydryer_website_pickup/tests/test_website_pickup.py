# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import re

from odoo.tests import HttpCase, new_test_user, tagged

from odoo.addons.earlydryer_logistics.tests.common import LogisticsCommon


@tagged("post_install", "-at_install")
class TestWebsitePickup(LogisticsCommon, HttpCase):
    def _page(self, url):
        response = self.url_open(url)
        self.assertEqual(response.status_code, 200, url)
        return response.text

    def _csrf(self, html):
        return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)

    def _form(self, **vals):
        html = self._page(f"/pickup?area_id={self.area_near.id}&date={self.tomorrow}")
        slot = re.search(r'name="slot_key" required="required" value="([^"]+)"', html)
        client_ref = re.search(r'name="client_ref" value="([^"]+)"', html)
        return {
            "csrf_token": self._csrf(html),
            "area_id": self.area_near.id,
            "slot_key": slot.group(1),
            "client_ref": client_ref.group(1),
            "name": "T Web Customer",
            "phone": "0809 444 5566",
            "street": "7 T Avenue",
            "landmark": "T yellow gate",
            "notify_opt_in": "1",
            **vals,
        }

    def test_book_follow_and_cancel(self):
        html = self._page("/pickup")
        self.assertIn(self.area_near.name, html)
        self.assertNotIn(self.area_unserved.name, html.split('id="callback"')[0])
        form = self._form()
        response = self.url_open("/pickup/book", data=form)
        self.assertEqual(response.status_code, 200)
        self.assertIn("/pickup/track", response.url)
        stop = self.Stop.search([("client_ref", "=", form["client_ref"])])
        self.assertEqual(stop.source, "website")
        self.assertEqual(stop.state, "scheduled")
        self.assertIn(stop.name, response.text)
        # the same form sent twice books once
        self.url_open("/pickup/book", data=form)
        self.assertEqual(
            self.Stop.search_count([("client_ref", "=", form["client_ref"])]), 1
        )
        response = self.url_open(
            "/pickup/cancel",
            data={
                "csrf_token": self._csrf(response.text),
                "ref": stop.name,
                "token": stop.sudo().access_token,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(stop.state, "cancelled")

    def test_errors_and_spam(self):
        form = self._form(phone="12")
        response = self.url_open("/pickup/book", data=form)
        self.assertEqual(response.status_code, 200)
        self.assertIn("alert-danger", response.text)
        self.assertFalse(self.Stop.search([("client_ref", "=", form["client_ref"])]))
        form = self._form(website_hp="http://spam")
        self.url_open("/pickup/book", data=form)
        self.assertFalse(self.Stop.search([("client_ref", "=", form["client_ref"])]))
        self.assertEqual(
            self.url_open("/pickup/track?ref=nothing&token=x").status_code, 404
        )

    def test_portal_lists_pickups(self):
        user = new_test_user(
            self.env, login="t_portal_pickup", groups="base.group_portal"
        )
        user.partner_id.phone = "0809 777 8899"
        self.env["earlydryer.logistics.booking"].book_pickup(
            {
                "name": "T",
                "phone": "+234 809 777 8899",
                "area_id": self.area_near.id,
                "street": "1 T Way",
                "slot_key": self._first_slot_key("pickup"),
                "source": "website",
            }
        )
        stop = self.Stop.search([("partner_id", "=", user.partner_id.id)])
        self.assertTrue(stop)
        self.authenticate("t_portal_pickup", "t_portal_pickup")
        html = self._page("/my/pickups")
        self.assertIn(stop.name, html)
        self.assertIn("/pickup/track?", html)
