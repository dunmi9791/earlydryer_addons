# Copyright 2026 Secteur
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
# ruff: noqa: F401 -- Odoo registers modules through these imports.
# Load source extensions before initializing the reporting SQL views.
# ruff: noqa: I001

from . import laundry_job_item
from . import laundry_job_stage_log
from . import report_qc_event
from . import report_job
from . import report_item
from . import report_stage
from . import report_sales
from . import report_discount
from . import report_ledger
from . import kpi
from . import earlydryer_branch
from . import notify_alert_rule
from . import notify_eod_report
from . import report_subscription
from . import mis_report_instance
from . import report_pack
from . import res_config_settings
