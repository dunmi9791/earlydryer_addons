# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import models


class ReportWhtRemittanceXlsx(models.AbstractModel):
    _name = "report.earlydryer_accounting_ng.report_wht_remittance_xlsx"
    _inherit = "report.report_xlsx.abstract"
    _description = "Earlydryer WHT Remittance XLSX"

    def generate_xlsx_report(self, workbook, data, wizards):
        wizards._earlydryer_check_right()
        bold = workbook.add_format({"bold": True})
        money = workbook.add_format({"num_format": "#,##0.00"})
        money_bold = workbook.add_format({"num_format": "#,##0.00", "bold": True})
        date_format = workbook.add_format({"num_format": "yyyy-mm-dd"})
        headers = [
            self.env._("Vendor"),
            self.env._("TIN"),
            self.env._("Invoice"),
            self.env._("Entry"),
            self.env._("Date"),
            self.env._("Category"),
            self.env._("Vendor Type"),
            self.env._("Gross Amount"),
            self.env._("Rate (%)"),
            self.env._("WHT Amount"),
        ]
        for wizard in wizards:
            sheet = workbook.add_worksheet(
                f"WHT {wizard.date_from} {wizard.date_to}"[:31]
            )
            sheet.write(0, 0, self.env._("WHT remittance"), bold)
            sheet.write(
                1,
                0,
                f"{wizard.company_id.name} - {wizard.date_from} / {wizard.date_to}",
            )
            for column, header in enumerate(headers):
                sheet.write(3, column, header, bold)
            row = 4
            rows = wizard._earlydryer_rows()
            for values in rows:
                sheet.write(row, 0, values["vendor"])
                sheet.write(row, 1, values["tin"])
                sheet.write(row, 2, values["invoice"])
                sheet.write(row, 3, values["number"])
                sheet.write_datetime(row, 4, values["date"], date_format)
                sheet.write(row, 5, values["category"] or "")
                sheet.write(row, 6, values["vendor_type"] or "")
                sheet.write_number(row, 7, values["base"], money)
                sheet.write_number(row, 8, values["rate"])
                sheet.write_number(row, 9, values["wht"], money)
                row += 1
            sheet.write(row, 0, self.env._("Total"), bold)
            sheet.write_number(row, 7, sum(v["base"] for v in rows), money_bold)
            sheet.write_number(row, 9, sum(v["wht"] for v in rows), money_bold)
            sheet.set_column(0, 0, 32)
            sheet.set_column(1, 6, 16)
            sheet.set_column(7, 9, 16)
