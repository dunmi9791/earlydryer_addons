# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import ast
import json

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.rendering_tools import parse_inline_template, render_inline_template
from odoo.tools.safe_eval import safe_eval

from ..tools import sms_size


class NotifyTemplate(models.Model):
    _name = "earlydryer.notify.template"
    _description = "Notification Template"
    _inherit = ["mail.render.mixin"]
    name = fields.Char(required=True, translate=True)
    event_id = fields.Many2one(
        "earlydryer.notify.event", required=True, ondelete="cascade"
    )
    channel = fields.Selection(
        [("whatsapp", "WhatsApp"), ("sms", "SMS")], required=True
    )
    branch_id = fields.Many2one("earlydryer.branch")
    body = fields.Text(required=True)
    approved = fields.Boolean(
        help="Enable only after the actual WhatsApp template is approved by Meta/BSP."
    )
    meta_template_name = fields.Char()
    meta_language = fields.Char(default="en")
    param_expressions = fields.Text(
        default="[]", help="JSON array of ordered Odoo safe-eval expressions. No Jinja."
    )
    character_count = fields.Integer(compute="_compute_size")
    segment_count = fields.Integer(compute="_compute_size")
    _template_unique = models.Constraint(
        "unique(event_id, channel, branch_id)", "One template per event/channel/plant."
    )

    def init(self):
        # SQL UNIQUE treats NULL plants as distinct; a partial index protects the global default.
        self.env.cr.execute("""CREATE UNIQUE INDEX IF NOT EXISTS notify_template_default_unique
            ON earlydryer_notify_template (event_id, channel) WHERE branch_id IS NULL""")

    @api.depends("body")
    def _compute_size(self):
        for t in self:
            t.character_count, t.segment_count = sms_size(t.body or "")

    @api.constrains("param_expressions")
    def _check_params(self):
        for t in self:
            try:
                expressions = json.loads(t.param_expressions or "[]")
                if not isinstance(expressions, list) or not all(
                    isinstance(e, str) for e in expressions
                ):
                    raise ValueError()
            except (ValueError, TypeError):
                raise ValidationError(
                    self.env._("Parameters must be a JSON list of expressions.")
                ) from None

    def _render(self, record, context):
        self.ensure_one()
        # The Odoo 19 inline engine with an explicit, small evaluation context.
        variables = {"object": record, "ctx": context, "user": self.env.user}
        instructions = parse_inline_template(self.body)
        expressions = [e for _, e, _ in instructions if e] + json.loads(
            self.param_expressions or "[]"
        )
        for expression in expressions:
            tree = ast.parse(expression, mode="eval")
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and (
                    node.attr.startswith("_")
                    or node.attr
                    in {"env", "sudo", "with_user", "with_context", "with_company"}
                ):
                    raise ValueError("Restricted template attribute")
                if isinstance(node, ast.Call) and (
                    not isinstance(node.func, ast.Name)
                    or node.func.id not in {"str", "len", "round"}
                ):
                    raise ValueError("Restricted template call")
                if isinstance(
                    node,
                    (
                        ast.Lambda,
                        ast.NamedExpr,
                        ast.ListComp,
                        ast.SetComp,
                        ast.DictComp,
                        ast.GeneratorExp,
                    ),
                ):
                    raise ValueError("Restricted template expression")
        variables.update(str=str, len=len, round=round)
        body = render_inline_template(instructions, variables)
        params = [
            str(safe_eval(expr, variables))
            for expr in json.loads(self.param_expressions or "[]")
        ]
        if any(not value for value in params):
            raise ValueError("empty parameter")
        return body, params
