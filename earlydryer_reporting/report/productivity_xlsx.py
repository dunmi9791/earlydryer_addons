# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import models

from ..tools import dates, scope


class ProductivityXlsx(models.AbstractModel):
    _name = "report.earlydryer_reporting.productivity_xlsx"
    _description = "Earlydryer Productivity XLSX"
    _inherit = "report.report_xlsx.abstract"

    def generate_xlsx_report(self, workbook, data, records):
        branches = scope(self.env, data.get("branch_ids", []), staff=True)
        start, end, _ = dates(data["date_from"], data["date_to"])
        service = self.env["earlydryer.kpi"]
        rows = service.compute(["productivity"], branches.ids, start, end)[
            "productivity"
        ]["rows"]
        header = workbook.add_format({"bold": True})
        for branch in branches:
            sheet = workbook.add_worksheet(
                (str(branch.id) + " " + branch.name)[:31].replace("/", "-")
            )
            sheet.write_row(
                0,
                0,
                [
                    self.env._("Employee"),
                    self.env._("Stage"),
                    self.env._("Moves"),
                    self.env._("Items"),
                    self.env._("Average hours"),
                ],
                header,
            )
            for index, row in enumerate(
                [x for x in rows if x["earlydryer_branch_id"] == branch.id], 1
            ):
                sheet.write_row(
                    index,
                    0,
                    [
                        row["employee"] or self.env._("Unassigned"),
                        row["stage"],
                        row["moves"],
                        row["items"],
                        row["hours"],
                    ],
                )
            sheet.set_column(0, 1, 25)
