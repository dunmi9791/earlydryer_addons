# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from dateutil.relativedelta import relativedelta
from odoo import _, fields
from odoo.exceptions import AccessError, ValidationError

LAGOS = ZoneInfo("Africa/Lagos")
DASHBOARD_GROUPS = (
    "group_branch_manager",
    "group_operations_manager",
    "group_finance",
    "group_management",
    "group_admin",
)
STAFF_GROUPS = (
    "group_branch_manager",
    "group_operations_manager",
    "group_hr",
    "group_management",
    "group_admin",
)


def has_any(env, groups):
    return env.su or any(env.user.has_group("earlydryer_base." + g) for g in groups)


def scope(env, branch_ids, staff=False):
    if not has_any(env, STAFF_GROUPS if staff else DASHBOARD_GROUPS):
        raise AccessError(env._("You do not have access to these reports."))
    allowed = env.user._earlydryer_allowed_branches().filtered(
        lambda b: b.company_id in env.companies
    )
    if branch_ids:
        allowed = allowed.filtered(lambda b: b.id in set(branch_ids))
    if len(allowed.company_id.currency_id) > 1:
        raise ValidationError(env._("Select plants using the same company currency."))
    return allowed


def dates(date_from, date_to, compare="previous"):
    start, end = fields.Date.to_date(date_from), fields.Date.to_date(date_to)
    if not start or not end or start > end:
        raise ValidationError(_("Choose a valid date range."))  # pylint: disable=prefer-env-translation
    if compare not in ("previous", "year"):
        raise ValidationError(_("Unknown comparison period."))  # pylint: disable=prefer-env-translation
    previous = (
        (start - timedelta(days=(end - start).days + 1), start - timedelta(days=1))
        if compare == "previous"
        else (start - relativedelta(years=1), end - relativedelta(years=1))
    )
    return start, end, previous


def utc_bounds(start, end):
    return tuple(
        datetime.combine(d, time.min, tzinfo=LAGOS)
        .astimezone(ZoneInfo("UTC"))
        .replace(tzinfo=None)
        for d in (start, end + timedelta(days=1))
    )
