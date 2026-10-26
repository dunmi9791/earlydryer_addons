# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo.tests import HttpCase, tagged

from odoo.addons.earlydryer_tagging.models.ir_actions_report import PAPERFORMAT_CTX

from .common import TaggingCommon

TAG_REPORT = "earlydryer_tagging.report_garment_tag"
BAG_REPORT = "earlydryer_tagging.report_bag_label"


@tagged("post_install", "-at_install")
class TestLabels(TaggingCommon, HttpCase):
    """HttpCase: wkhtmltopdf fetches the report CSS from the test server,
    which must serve it inside the test transaction."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param("report.url", cls.base_url())
        cls.partner.name = "Adaeze Okonkwo"
        cls.job = cls._create_job([(cls.suit_dc, 1, None)], express=False)
        cls.Report = cls.env["ir.actions.report"].with_context(
            force_report_rendering=True
        )

    def _pdf(self, report, res_ids, paperformat_xmlid=None):
        Report = self.Report
        if paperformat_xmlid:
            Report = Report.with_context(
                **{PAPERFORMAT_CTX: self.env.ref(paperformat_xmlid).id}
            )
        content, kind = Report._render_qweb_pdf(report, res_ids)
        self.assertEqual(kind, "pdf")
        self.assertTrue(content.startswith(b"%PDF"))
        return content

    def test_garment_tags_render(self):
        items = self.job.item_ids
        for xmlid in (
            "earlydryer_tagging.paperformat_tag_thermal_50x25",
            "earlydryer_tagging.paperformat_tag_heatseal_60x15",
            "earlydryer_tagging.paperformat_label_sheet_a4",
        ):
            self._pdf(TAG_REPORT, items.ids, xmlid)
        # the plant's size by default
        self._pdf(TAG_REPORT, items.ids)

    def test_bag_label_renders(self):
        self.job.express = True
        self._pdf(BAG_REPORT, self.job.ids)
        self._pdf(
            BAG_REPORT, self.job.ids, "earlydryer_tagging.paperformat_label_sheet_a4"
        )

    def test_label_content(self):
        items = self.job.item_ids
        html = self.Report._render_qweb_html(TAG_REPORT, items.ids)[0].decode()
        for item in items:
            self.assertIn(item.tag_code, html)
        self.assertIn("Adaeze O.", html)
        self.assertNotIn(self.partner.phone, html, "never the phone number")
        self.assertIn("1/2</span>", html)
        self.assertIn(self.svc_dc.code, html)
        self.assertIn("data:image/png;base64", html, "barcode embedded")
        bag = self.Report._render_qweb_html(BAG_REPORT, self.job.ids)[0].decode()
        self.assertIn(self.job.name, bag)
        self.assertIn("2 item(s)", bag)

    def test_layout_follows_paperformat(self):
        Report = self.env["report.earlydryer_tagging.report_garment_tag"]
        values = Report.with_context(
            **{
                PAPERFORMAT_CTX: self.env.ref(
                    "earlydryer_tagging.paperformat_tag_heatseal_60x15"
                ).id
            }
        )._get_report_values(self.job.item_ids.ids)
        self.assertEqual(values["layout"], "strip")
        self.branch_1.tag_label_paperformat_id = self.env.ref(
            "earlydryer_tagging.paperformat_label_sheet_a4"
        )
        self.assertEqual(
            Report._get_report_values(self.job.item_ids.ids)["layout"], "sheet"
        )
        report = self.env["ir.actions.report"]._get_report_from_name(TAG_REPORT)
        self.assertEqual(
            report._earlydryer_label_paperformat(TAG_REPORT, self.job.item_ids.ids),
            self.branch_1.tag_label_paperformat_id,
        )

    def test_zpl(self):
        self.branch_1.tag_zpl_template = (
            "^XA^FD{code}^FS^FD{job}|{garment}|{piece}|{nope}^FS^XZ"
        )
        self.partner.name = "Ada^Bad~Name"
        zpl = self.job._earlydryer_zpl()
        lines = zpl.strip().splitlines()
        self.assertEqual(len(lines), 2)
        item = self.job.item_ids[0]
        self.assertEqual(
            lines[0],
            f"^XA^FD{item.tag_code}^FS^FD{self.job.name}|{self.cat_suit.name}|1/2|{{nope}}^FS^XZ",
        )
        action = self.job.with_user(self.user_front_desk).action_download_zpl()
        self.assertEqual(action["type"], "ir.actions.act_url")
        self.branch_1.tag_zpl_template = "^FD{customer}^FS"
        self.assertEqual(
            self.job._earlydryer_zpl().splitlines()[0], "^FDAda Bad Name^FS"
        )
