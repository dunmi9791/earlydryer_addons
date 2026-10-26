# Reporting validation

Validated on 26 October 2026 using official Odoo Community 19.0
(`19.0-20261015`) and PostgreSQL 16 in the isolated cloud environment.
The user's WSL container and local database were not accessed or changed.
Only `earlydryer_reporting/` is added to the repository.

## Module tree

```text
earlydryer_reporting/
├── __init__.py, __manifest__.py, hooks.py, tools.py
├── README.rst, VALIDATION.md, .gitignore
├── models/
│   ├── kpi.py
│   ├── report_job.py, report_item.py, report_stage.py, report_sales.py
│   ├── report_discount.py, report_ledger.py, report_qc_event.py
│   ├── laundry_job_item.py, laundry_job_stage_log.py
│   ├── earlydryer_branch.py, notify_alert_rule.py, notify_eod_report.py
│   ├── report_subscription.py, report_pack.py, mis_report_instance.py
│   └── res_config_settings.py
├── views/ (analysis, dashboard action, subscriptions, settings)
├── security/ (ACLs and company/branch/recipient rules)
├── data/ (notification events/templates, queue functions, cron)
├── demo/demo.xml, demo_generator.py
├── report/ (pack QWeb/PDF, productivity XLSX)
├── wizards/ (explicit-period send, productivity export)
├── static/src/ (OWL header/section/tile/chart, XML, SCSS)
├── static/tests/dashboard_tour.js
└── tests/ (common, KPI correctness/security, packs, HttpCase, performance)
```

## Reproduction

Add this repository and the manifest's OCA dependencies to `addons_path`.
Install their Python requirements. Use disposable databases and a working
`wkhtmltopdf` for PDF output. The cloud helper `report-run.sh` wraps the official
image with those mounts and configuration; the equivalent Odoo commands are:

```sh
odoo -c CONF -d earlydryer_reporting_test -i earlydryer_reporting --without-demo=True --stop-after-init
odoo -c CONF -d earlydryer_reporting_test -u earlydryer_reporting --test-enable --test-tags /earlydryer_reporting --stop-after-init
odoo -c CONF -d earlydryer_reporting_test -i earlydryer_production -u earlydryer_reporting --test-enable --test-tags /earlydryer_reporting --stop-after-init
odoo -c CONF -d earlydryer_reporting_demo -i earlydryer_reporting --without-demo=False --stop-after-init
EARLYDRYER_PERF_TEST=1 odoo -c CONF -d earlydryer_reporting_test --test-enable --test-tags /earlydryer_reporting:TestPerformance --stop-after-init
```

A real Chrome executable and `websocket-client` are required for HttpCase.
Browser tests in this validation executed in Chrome; they were not skipped.

## Results

* Fresh installation without demo data succeeded. Empty KPI computation returned
  zeros, and the dashboard rendered its empty-period hint.
* The full suite with optional Production installed: **42 tests, 0 failures,
  0 errors**, one explicitly skipped optional benchmark. This includes a real
  dashboard tile tour, a 375 px layout check, weighed/estimated/mixed kilograms,
  stage source and exception checks, exact KPI/drill fixtures, EOD regression,
  recipient security, a daily EOD single-email regression and real MIS XLSX generation.
* Populated demo database without Production: **42 tests, 0 failures, 0 errors**,
  with three explicit skips (two optional Production cases and the benchmark).
  Browser fixtures also contain two plants and staff rows in no-demo databases.
* Fresh demo installation completed with 240 generated jobs dated 28 August–26
  October 2026, eight posted vendor bills and two additional closed/posted POS
  sessions. The demo generator is fixed-seed and uses dates relative to installation.
* The enabled benchmark passed separately: **1 test, 0 failures/errors,
  0.954 seconds** with Production installed. An earlier no-Production run was
  0.686 seconds. Both were below the one-second target; hardware/load will affect
  timings and the limitation below applies.
* Live owner and branch-manager sessions passed period/comparison/plant changes,
  order and expense drills, the productivity pivot and 375 px single-column
  layout. The stable `/odoo/earlydryer-dashboard` route worked for both users.
* Actual wkhtmltopdf output was rendered for weekly and monthly Send now packs.
  Weekly: one 35,846-byte PDF. Monthly: KPI PDF plus two MIS PDFs and two real
  XLSX files (five attachments). Both emails remained **outgoing**; no SMTP or
  messaging-provider delivery was attempted. Productivity XLSX also rendered.
* Core PWA routes were checked over HTTP: general manifest starts at `/odoo`,
  scoped-app-generated manifest starts/scopes at `/odoo/earlydryer-dashboard`,
  and the core service worker responds. Browser/OS installation itself needs the
  real HTTPS deployment and was not emulated as a successful phone installation.
* Ruff checks and formatting, Prettier JS/SCSS and pylint-odoo passed (10.00/10).
  Odoo registration imports and manifest literals have narrowly documented lint
  exceptions. No eslint/OCA pre-commit configuration exists in this checkout.
* No reporting-module warnings were emitted by the successful suite. Core's
  Chrome cleanup can warn about `chrome_crashpad` child processes after the
  successful browser tests; these are distinct from module failures.

The benchmark inserts 50,000 jobs, 50,000 garments and 50,000 stage rows across
both plants, analyzes the tables, and measures one complete monthly default KPI
call including comparison, drills and chart metadata. It rolls its fixture back.
It measures server computation, not browser rendering or network latency. It is
not a worst-case benchmark of 50,000 simultaneously unpaid jobs: exact live due
allocation deliberately uses the source ORM (see below).

## Implementation choices and source differences

* Actual source fields are `qc_state="rework"` and
  `earlydryer_released_unpaid`; source job totals and due balances are non-stored.
* Live job due uses the source ORM to preserve its POS-session FIFO, wallet and
  settlement allocation. Approximating it with a SQL residual would change the
  answer. Other calculations use parameterized SQL and share aggregates within
  one request, avoiding repeated scans; no persistent cache was added.
* Extra discount and posted-allocation views provide accurate commercial and
  analytic-share drill-downs without granting branch managers accounting access.
* EOD is overridden from this new module, preserving its public signature and
  keys without changing notifications files. Its legacy cash, POS-only discounts
  and current-closed-job snapshot remain compatible. Shared orders, value,
  ready/overdue and top-ups use canonical KPI computations; the added KPI section
  uses the broader documented dashboard definitions. The regression compares the
  entire original and new figure dictionaries on the same exact fixture.
* Optional Production columns are read at query time, so installing Production
  later does not freeze stage sources/counts to their fallback values.
* Core Community spreadsheet dashboards were inspected. The custom OWL action
  uses the bundled `web.chartjs_lib`; no Enterprise dependency or chart copy.
* Core Odoo's manifest, service worker and scoped-app routes are reused.
  README documents Android/iPhone steps and the stable dashboard route. A
  standalone session still needs online access; no offline analytics is promised.
* MIS uses fixed-date `mis.report.instance`, `compute()`,
  `_render_qweb_pdf("mis_builder.qweb_pdf_export", ...)` and
  `_render_xlsx("mis_builder.xls_export", ...)`. Generated instances have their
  own complete plant scope, including Total columns, and record rules. Existing
  accounting instances are preserved.
* New QC/missing/release history becomes exact after installation. Older records
  without timestamps cannot be assigned invented dates. README details fallbacks.

Business decisions still needed are listed in README: first-screen priorities
and targets, weighing practice, pack recipients/times, cross-plant permissions
and productivity follow-up. They do not block the implemented defaults.

## Cleanup and delivery

The disposable `earlydryer_reporting_test` and `earlydryer_reporting_demo`
databases and their filestores were removed after validation. The original
`earlydryer_dev` database/volumes were preserved and its app restored and checked
through the login form. Local test configuration, browser binaries and logs live
outside the repository under `/workspace/.earlydryer/`.

Work is committed on `feat/earlydryer-reporting`; no push or merge was performed.
