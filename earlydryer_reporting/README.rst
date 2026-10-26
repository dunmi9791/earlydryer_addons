====================
Earlydryer Reporting
====================

Odoo 19 Community owner dashboard, operational analysis, staff productivity and
scheduled performance packs. No Enterprise module or external chart library.
Requires earlydryer_notifications, mis_builder, report_xlsx, date_range and
web_responsive. Build/install only this add-on; existing module files are not
modified. See VALIDATION.md for the executed checks and their limits.

Dashboard and dates
===================

Reporting > Owner dashboard opens the OWL client action. Its stable route is::

    https://YOUR-ODOO-HOST/odoo/earlydryer-dashboard

The numeric action route /odoo/action-ID is also supported by core. Periods are
Today, Yesterday, This/Last week, This/Last month, This year and Custom. All date
boundaries use Africa/Lagos, including comparisons. Previous means the preceding
inclusive period of equal length; year means the same dates last year (Feb 29
clamps to Feb 28). Point-in-time numbers explicitly say Now; no historical balance
snapshot is invented and their comparison value is also the current value.

Management and Operations Manager users without an existing action_id receive
the dashboard as their home action at installation only. Existing choices are
preserved. New users created later can choose it in their preferences.

The dashboard fetches data in one earlydryer.kpi.compute call. Server-side group,
company and branch checks apply independently of the selector and UI. A manager
requesting another plant's ID cannot obtain that plant's numbers. Finance receives
no employee rows; HR can access productivity only and has no dashboard menu.

Orders taken is an operational figure from received jobs, including POS orders
whose sessions are still open. Posted revenue is a ledger figure allocated by
plant analytic percentage and appears only after the accounting is posted.
They deliberately appear side by side. Click a tile for the corresponding rows.
The new posted-allocation drill shows the allocated amount, avoiding misleading
full-line totals for a line split across plants.

Mobile home-screen setup
========================

The dashboard uses the same authenticated Odoo web client on desktop and phones.
It uses core Chart.js through loadBundle("web.chartjs_lib"), not a bundled copy.
OCA web_responsive provides the Community navigation adaptation. The dashboard
itself becomes one column below 600 px, with large click targets and charts below.

Core Odoo 19 provides /web/manifest.webmanifest (start_url /odoo),
/web/service-worker.js and /odoo/offline. Its manifest scope is /odoo and it uses
standalone display. No service worker or separate app is added here.

* Android/Chrome: sign in over HTTPS, open the dashboard URL, then Chrome menu >
  Install app or Add to Home screen (wording depends on Chrome).
* iPhone/Safari: sign in, open the dashboard URL, Share > Add to Home Screen,
  keep Open as Web App enabled where offered.
* A general Odoo installation can start at /odoo rather than the current action.
  Management/Operations home actions above make that open the dashboard. To
  install a shortcut scoped directly to the dashboard, core also supplies::

      /scoped_app?app_id=earlydryer_reporting&path=odoo%2Fearlydryer-dashboard&app_name=Earlydryer

  Core's scoped manifest then uses /odoo/earlydryer-dashboard as start_url/scope.
  Use the full HTTPS host URL before saving the shortcut. Session authentication
  and online access are still required; this is not an offline reporting app.

Data and exact definitions
==========================

Read-only SQL views: earlydryer.report.job (job), item (garment), stage (move) and
sales (POS/invoice line). Additional discount (POS/sale line) and ledger (posted
plant allocation) grains ensure discount/financial drills match their totals.
Invoices originating from POS are excluded from the invoice half of the sales
view, preventing retail double counting. Refunds use signed amounts. Operational
sales includes paid/done/invoiced POS and posted customer invoice/refund lines;
it is not a substitute for posted income-account balances.

The source's job amount_total/amount_due fields are non-stored. The job view
reconstructs order value from the source sales/POS totals (excluding settlement
lines where the source does). Due balances deliberately delegate to the source's
live residual allocation, including session FIFO, wallet credits and settlements.
That KPI uses a bounded ORM read of open source-backed jobs instead of a lossy
single-SQL approximation. The other aggregations use parameterized Odoo SQL.
No raw user values are interpolated into queries.

SQL-view initialization follows the source extensions. Item/stage views join
native tables directly rather than re-expanding the job aggregate/window view.
Added indexes, without editing another add-on:

* laundry_job (earlydryer_branch_id, received_on)
* laundry_job (company_id, partner_id, received_on, id)
* laundry_job_stage_log (earlydryer_branch_id, date)

The reporting extension records new QC rework/pass and missing/found events, and
snapshots whether a release move had a balance. Current source names include
qc_state=rework and earlydryer_released_unpaid. Historical Production rework rows
are used when present; matching newly recorded events are not counted twice.
Without historical records, older QC passes can only use the item's last qc_date.
Previously missing flags with no timestamp cannot be attributed to an invented
day. Counts become complete for new transitions after installation.

KPI definitions
---------------

* ``orders_count`` — Non-cancelled jobs received in the period.
* ``orders_value`` — Sum of source job totals for those received jobs; operational orders taken.
* ``items_count`` — Garment item rows belonging to jobs received in the period.
* ``avg_order_value`` — Orders taken divided by orders received; zero for an empty period.
* ``retail_sales`` — Signed retail net sales from POS/invoices, excluding POS-origin invoice duplicates.
* ``revenue_posted`` — Negative posted income/income_other balance times plant analytic share.
* ``collected_count`` — Distinct jobs with a collected stage event in the period.
* ``delivered_count`` — Distinct jobs with a delivered stage event in the period.
* ``turnaround_avg_h`` — Ready-in-period jobs: average received-to-ready hours.
* ``turnaround_p90_h`` — Ready-in-period jobs: continuous 90th percentile of received-to-ready hours.
* ``on_time_pct`` — Percentage of ready-in-period jobs ready no later than promised.
* ``overdue_count`` — Current open overdue jobs using the source state/promise exclusions; period ignored.
* ``ready_uncollected_count`` — Jobs currently ready; period ignored.
* ``uncollected_count`` — Distinct jobs reaching uncollected in the period.
* ``unpaid_balance`` — Current due on open jobs; separate positive posted receivables ageing by maturity (0–30, 31–60, 60+ days). Receivables and jobs are not added together because they can overlap.
* ``unpaid_releases`` — Distinct jobs with a release-stage balance snapshot in the period.
* ``discount_value`` — POS and confirmed sale-line gross times discount percentage, avoiding linked sale/POS line duplication; includes approved-discount count.
* ``discount_pct`` — Discount value divided by gross commercial value.
* ``new_customers`` — Period customers whose first non-cancelled company job falls within the period, including a first job at another plant.
* ``repeat_customers`` — Distinct period customers whose first company job precedes the period.
* ``repeat_rate`` — Percentage of period orders belonging to those pre-period customers.
* ``wallet_topups`` — Posted top-up amounts dated in the period, by transaction plant.
* ``wallet_balance`` — Signed posted transactions now, attributed to their plants; full company scope also includes unassigned historical transactions.
* ``expenses`` — Posted expense/direct-cost/depreciation balances allocated by plant; five largest accounts.
* ``cost_per_kg`` — Direct costs and configured consumables, excluding retail COGS, divided by processed kilograms; see method below.
* ``rework_rate`` — Distinct items failed in period / distinct items passed in period times 100 (can exceed 100).
* ``missing_items`` — Distinct items flagged missing in the period, including items subsequently found.
* ``productivity`` — Employee/from-stage rows: moves, items, average elapsed hours before the move, plus unassigned production moves.

Cost per kg and productivity
============================

Only completed wash-batch weights in the period are counted as weighed kg; dry
batches are excluded to avoid counting the same load twice. Items processed
(washed stage or ready in the period) without a weighed batch use the garment
category's average_weight_kg. Weighed items are removed from the estimated part.
The result always carries weighed / estimated / mixed and both component weights.
Missing category weights produce zero estimated kg, not a fabricated weight.
Future site-cost modules can extend the direct-cost calculation explicitly.

Staff productivity is grouped by the stage being left (from_state): duration is
hours spent before the move, not a promise of labour time. Production's item_count
and source are used when installed; otherwise item relations/job count and form
source are used. Exception filters identify missing employees, cross-plant moves
and minutes per garment below the configurable minimum (default 0.5). The XLSX
export has one sheet per allowed plant. HR has read-only productivity access.

Productivity is an indicator for coaching, not for pay. Payroll commissions are
calculated separately in the payroll module later.

Scheduled packs and EOD compatibility
=====================================

Subscriptions are editable by Management/Admin or their own recipient. Users
cannot change ownership or configure plants beyond their access. Email-only
owners without logins require explicit plants and a Management-created record.

* Single-plant branch managers receive a daily subscription by default. Daily
  subscriptions merge into the existing plant EOD delivery; they do not enqueue
  a second standalone pack. The branch EOD time controls delivery. Existing EOD
  recipient emails gain a KPI section; subscribed recipients not already on the
  branch recipient list receive that same cash report and KPI email once.
* Management users receive weekly and monthly subscriptions. Weekly covers the
  last complete Monday–Sunday period; monthly covers the last complete calendar
  month. The cron catches up missed runs after downtime. Default send time is
  08:00 Africa/Lagos and can be changed.
* A 15-minute cron enqueues packs through root.earlydryer_reporting. A unique
  subscription/period/run key prevents duplicate scheduled delivery. Send now
  accepts explicit dates and creates a distinct manual resend run.

Pack emails enter the outgoing mail queue and their send operation is also a
queue job. They include a KPI PDF, plant splits, top service types, turnaround,
ageing, expenses, weight method and permitted productivity data. Monthly packs
include four additional attachments: P&L by plant PDF/XLSX and P&L by service line
PDF/XLSX. The existing accounting P&L template is reused via mis.report.instance,
compute(), core PDF rendering and report_xlsx export. Fresh date-fixed instances
have an overall selected-plant analytic domain, including Total/service columns;
existing accounting report instances are never mutated. Generated instances have
additional branch record rules so a pack cannot expose another plant.

The original notifications _earlydryer_eod_figures(date) signature, keys and cash
figures are preserved by moving its calculation into the KPI service and
inheriting the branch method here. A regression test compares the legacy and new
outputs on a known day. Legacy EOD discounts are POS discounts and completions
are the current closed-date snapshot; the dashboard's commercial discounts and
stage-event completions have broader definitions. These legacy keys are retained
for compatibility; the appended, labelled KPI section uses the exact same compute
API as the dashboard/packs. No notifications source file is changed.

WhatsApp events report_weekly and report_monthly use draft templates:

* earlydryer_report_weekly / earlydryer_report_monthly
* Suggested category: UTILITY; language: en; submit for provider approval.
* Text: ``{{1}}: {{2}}. Call {{3}}.``
* Parameters: plant name, short period/orders/sales/on-time summary, plant phone.

Configure approved templates and real providers in Notifications before enabling
WhatsApp subscriptions. Consent, opt-outs, quiet-hour/window rules and SMS fallback
remain the notifications module's responsibility. No real provider is configured
by this add-on. Outgoing email needs the deployment's SMTP configuration.

Queue configuration in the actual deployment (review existing values)::

    [options]
    server_wide_modules = base,web,queue_job
    workers = 2
    [queue_job]
    host = 127.0.0.1
    port = 8069
    channels = root:2,root.earlydryer_notify:1,root.earlydryer_reporting:1

Development, demo and extensions
================================

The deterministic demo generator uses seed 9791 and 60 days relative to the
installation date. It creates historical sales/jobs/items/stages for both demo
plants, quality/missing events, cash wallet advances, posted plant expenses and
posted POS sessions. It is invoked only by demo XML under install_demo; normal
installation does not seed business activity.

Use throwaway databases to install and test::

    odoo -c <conf> -d <test> -i earlydryer_reporting --without-demo=False --stop-after-init
    odoo -c <conf> -d <test> -u earlydryer_reporting --test-enable --test-tags /earlydryer_reporting --stop-after-init

Browser tests need Chrome and websocket-client in the test environment. The
performance test is skipped unless EARLYDRYER_PERF_TEST=1; it creates 50,000 jobs
with 50,000 garments/stage rows using SQL only inside a rolled-back test fixture.
No persistent KPI cache is created; repeated aggregates are shared only within
a compute call. The measured 50,000-job/garment/stage benchmark is recorded in
VALIDATION.md. JIT is disabled transaction-locally during KPI calculation to avoid
LLVM startup overhead on interactive reports; no server setting is changed. Keep existing isolated checkouts rather than creating worktrees.

To add a KPI: add one private method to earlydryer.kpi and one REGISTRY entry
(label, unit, method, drill model and period semantics). Apply branch scope before
queries, use SQL parameters, return plain JSON, define a matching drill and add
an exact-answer fixture. Optional Production is detected through model/field
checks; it is intentionally absent from the manifest dependencies.

Questions for Earlydryer
========================

* Which KPIs should lead the first screen, and what on-time/turnaround/rework
  targets should colour tiles against? Current colours show comparison direction.
* Will wash loads be weighed consistently, and who maintains estimated weights?
* Who receives daily/weekly/monthly packs, by which channels and at what times?
* May branch managers see other plants? The current implementation restricts them
  to their configured allowed plants.
* How will productivity be used for coaching and exception follow-up?
