# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import api, models


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    def _earlydryer_pos_rule_ids(self, rules):
        """``{employee_id: [rule ids]}``: the rules each employee may approve,
        from the groups of the employee's user (none without a user)."""
        result = {}
        for employee in self.sudo():
            groups = employee.user_id.all_group_ids
            result[employee.id] = [
                rule.id for rule in rules.sudo() if rule.approver_group_id in groups
            ]
        return result

    @api.model
    def _load_pos_data_read(self, records, config):
        read_records = super()._load_pos_data_read(records, config)
        if not config.earlydryer_enabled:
            return read_records
        Rule = self.env["earlydryer.approval.rule"].sudo()
        rules = Rule.search(
            Rule._earlydryer_pos_rule_domain(config.earlydryer_branch_id)
        )
        rule_ids = records._earlydryer_pos_rule_ids(rules)
        branches = {
            employee.id: employee.earlydryer_branch_id.id for employee in records.sudo()
        }
        for employee in read_records:
            # approvers are limited to the till's plant (or no plant)
            employee["_earlydryer_branch_id"] = branches.get(employee["id"]) or False
            # the hashed PIN (_pin) comes from pos_hr; plain PINs never leave
            employee["_earlydryer_rule_ids"] = rule_ids.get(employee["id"], [])
        return read_records
