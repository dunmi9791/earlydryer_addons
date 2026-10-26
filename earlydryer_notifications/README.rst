========================
Earlydryer Notifications
========================

Odoo 19 Community notifications for Earlydryer. No Enterprise WhatsApp,
SMS IAP or paid Odoo messaging service is used. Only this add-on is changed.
Outbound provider calls, replies, webhook processing, alert delivery and EOD
rendering/email delivery run through OCA queue_job.

Installation and jobrunner
==========================

Install after earlydryer_accounting_ng and queue_job. Python requests ships
with Odoo. Use the existing isolated checkout; no additional worktree is needed.
Do not edit production configuration as part of installing this add-on. Add these
lines to the actual deployment's odoo.conf after reviewing its existing values::

    [options]
    server_wide_modules = base,web,queue_job
    workers = 2

    [queue_job]
    channels = root:2,root.earlydryer_notify:1
    host = 127.0.0.1
    port = 8069

Also configure the runner's host, port and database credentials for the actual
network topology. See OCA queue_job 19.0 README. With HTTPS termination, set
queue_job's scheme/host/port settings accordingly. A running HTTP service alone
does not establish that the jobrunner is active; look for "queue job runner ready"
and verify a log-only message reaches sent. Never run synchronous queue context
in production. Tests use trap_jobs and invoke the trapped worker methods without
calling external APIs.

Administration > Notifications > Providers selects the first active provider
by sequence within the message's company and channel. No real providers are
shipped in normal data. Demo data contains log-only providers; they never make
HTTP requests. Templates are drafts, even in demo. Only log-only providers may
use drafts. Activate real WhatsApp templates only after provider approval.

Meta Cloud configuration
========================

Create the Meta business app and WhatsApp business account, register the
verified business phone number, grant the token the appropriate WhatsApp
messaging permissions, and enter phone number ID, business account ID, token,
app secret and webhook verify token in an Administrator-only provider.
Copy its computed webhook URL into Meta and subscribe to messages. Configure
a supported Graph API version explicitly. The deployment's Meta documentation
was network-blocked during development, so no guessed "current stable" version
is silently selected. Verify the current version in Meta's dashboard/docs.

Official references (must be reviewed before connecting a real business)::

    https://developers.facebook.com/docs/whatsapp/cloud-api/reference/messages
    https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks
    https://developers.facebook.com/docs/graph-api/changelog/versions

Messages POST to /<graph_version>/<phone_number_id>/messages. Automatic
WhatsApp messages always use approved template messages, with ordered body
parameters. Free text is allowed only within 24 hours of the inbound message;
this is checked again by the worker, so an expired queued reply is refused.
The verification GET returns hub.challenge only for the matching verify token.
POST requires the random URL token and an X-Hub-Signature-256 HMAC-SHA256 of
the exact raw body with the app secret. Cross-number callbacks are ignored.

Tokens, app secrets, verify tokens, random path tokens and generic header/body
configuration are excluded from auditlog values. Never paste tokens into
chatter, demo files, test fixtures, URLs, or source control. Test fixtures use
clearly labelled synthetic secrets only. No real credentials were requested.

The connection test is queued and performs only a harmless Meta GET; generic
providers perform configuration validation without sending. Test sends are
queued. A real WhatsApp test requires an approved template; the credentials and
recipient must be provided securely by the operator.

Generic SMS/WhatsApp gateway
============================

No Nigerian gateway or sender ID has been selected. Termii, BulkSMSNigeria and
Africa's Talking are examples, not recommendations or active defaults. Use an
HTTPS URL (redirects disabled), POST or PUT, JSON or form encoding, and JSON
objects for headers and body. Example body configuration::

    {"to":"{to}","from":"{sender}","sms":"{text}","type":"plain"}

Example header configuration::

    {"Authorization":"Bearer {api_token}"}

Available placeholders: {to}, {sender}, {text}, {template}, {params_json} and
{api_token}. JSON is parsed before substitution: quotes and newlines in text
remain escaped correctly. JSON-path settings use simple dotted dictionary keys,
e.g. data.success, data.message_id, error.code and data.cost. A success path is
interpreted as truthy/falsey; configure an appropriate gateway response field.
No provider response bodies are copied into errors. HTTP timeouts are 10 seconds.

Generic webhook senders must sign callbacks with the configured app_secret using
the same raw-body HMAC header and map the gateway-specific payload to::

    {"events":[{"kind":"inbound","external_id":"gateway-unique-id",
                "phone":"+2348031234567","body":"STOP"}]}

Status events use kind=status, external_id, state and optional error_code.
Inbound media is a provider reference only and is never downloaded.

Consent and sending policy
==========================

The intake checkbox defaults on for newly created contacts with a valid phone.
Suggested wording: "Send order and payment updates by WhatsApp/SMS. Reply STOP
to stop." Earlydryer must approve it before customer use. Existing contacts are
not retroactively opted in. Consent appears on the backend partner form, the
standard POS customer editor and the laundry quick-create dialog. Offline
quick-create preserves the checkbox on the order; matching an opted-out contact
never silently re-enables it. STOP and START work on both channels, recording
the date and source. STOP confirmations are the sole opt-out exemption.

Non-urgent customer notifications are held during 21:00-07:00 Africa/Lagos by
default. Set both times equal to disable quiet hours. Payment received and out
for delivery are urgent by default. Staff events are not subject to quiet hours.
Queued messages recheck consent and service windows before sending.

The event API is earlydryer.notify.message.notify(event_code, record,
partner=None, phone=None, context=None). Hooks supply occurrence identifiers.
Identical occurrences are deduplicated under database locks. A job state is
normally notified once ever; enabling allow_repeat permits subsequent actual
transitions. Other events use dedupe_minutes; separate real occurrences can be
permitted with allow_repeat. A message queued twice is sent only once.

Network/5xx/rate errors get 1, 5, 15 and 60 minute retries, then fail after five
attempts. Application retries schedule a successor queue job instead of raising
RetryableJobError: raising would roll back the attempt log and database rate
counter. Unexpected queue/processing failures still use queue_job's retry
mechanism. Rate counters are database-row locked per provider and minute.
Permanent WhatsApp failures create a linked SMS fallback when allowed. Meta
131026 is treated as unavailable/undeliverable (Meta does not reliably distinguish
"not on WhatsApp" from other undeliverable cases); operators can reset the flag.
Opt-out errors stop further customer messages. Administrator activities flag
configuration and final-send failures. Business transactions remain successful.

Bot and inbox
=============

Keywords: STATUS, TRACK, WHERE IS MY ORDER, a job number, a valid printed tag,
BALANCE, HELP, MENU, STOP, START. The bot matches normalized phone numbers,
prefers the contact with the newest job, and reveals at most five open jobs owned
by contacts with that exact phone in the provider's company. Invalid tag check
digits never trigger tag lookup. Wallet balance stays within the same company.

Unknown messages become Needs reply with a plant Customer Service activity
(manager/Admin fallback) and one acknowledgement per phone per four hours.
SMS only handles STOP/START automatically; other messages need staff replies.
Inbox actions: Assign to me, Reply, Close, Open jobs and Recent messages. Outside
the WhatsApp window a reply needs an approved template. Front Desk cannot reply.
Unknown-phone messages are visible to Customer Service but cannot disclose
customer data. Branch and company record rules protect inbox and outbox.

Alerts and EOD
==============

Placeholder rules: overdue digest 10:00/15:00; discounts above 10%; any
unpaid release/credit; scan mismatch, damage and wallet overdraw; job creation
failure to Administrator. Rules support activity/email/WhatsApp/SMS and scoped
groups, named users or opted-in staff contacts. Staff phone numbers reuse the
user contact phone, falling back to the linked employee mobile phone. Branch recipients are filtered
against allowed plants, with all-branch users included only when selected by the
rule. Overdue thresholds are hours; credit thresholds are currency amounts.
Digest slots and alert occurrences are recorded transactionally to avoid repeats.

The branch Notifications tab configures EOD time (20:00 Lagos), email and
WhatsApp recipients. The 15-minute cron schedules one report per branch/day.
Manual Send EOD report now chooses a date and creates an explicit resend run.
Reports contain order totals, completion counts, current ready/overdue backlog,
paid POS payments by method, discounts, unpaid releases, posted wallet top-ups
and scan mismatches. The reusable method is
earlydryer.branch._earlydryer_eod_figures(date).
Current backlog is a live snapshot, not a historical reconstruction of stages.
The financial PDF is the existing accounting daily-cash QWeb report, attached
to the email. WhatsApp receives a short summary; PDF media upload is deliberately
omitted. Email delivery requires the deployment's outgoing mail server.

Real hook names: earlydryer_released_unpaid and _earlydryer_after_sync;
_daily cash report data comes from the existing accounting QWeb report action.
Production damage is a soft override, without a module dependency. Logistics
pickup/failure and complaint events have templates now but no invented triggers.
The existing Python phone helper remains earlydryer_wallet.tools.normalize_ng_phone;
the POS JavaScript helper is reused in the client. They run in different runtimes,
so no other module was changed just to combine them.

Retention and audit
===================

Default body retention: 365 days. The cron clears outbound bodies, parameter
values, render context, error text, inbound bodies and media references while
keeping metadata and counts/costs. Raw webhook receipts are deleted after 30 days.
Provider, template and alert-rule writes are audited. Provider secret fields
are excluded using auditlog 19 fields_to_exclude_ids. Audit exclusions mean
old/new secret values are never retained, rather than storing masked copies.

Verification
============

Use throwaway databases. Never change/drop a production database::

    odoo -c <conf> -d <throwaway> -i earlydryer_notifications --without-demo=False --stop-after-init
    odoo -c <conf> -d <throwaway> -u earlydryer_notifications --test-enable --test-tags /earlydryer_notifications --stop-after-init

See VALIDATION.md for executed commands, exact results and deployment limitations.

Decisions required from Earlydryer
==================================

* WhatsApp provider (Meta direct or BSP), verified business number and supported Graph version.
* SMS gateway and registered sender ID (at most 11 characters).
* Approved intake consent wording and final message texts; Meta template approver.
* Quiet hours and urgent event exemptions.
* Manager recipients, channels, discount/credit/overdue thresholds and digest times.
* EOD recipients and time per plant.
* Whether to enable the collected/thank-you event (off by default).
* Retention period, outgoing email server and operational ownership of failures.

WhatsApp template submission list
=================================

All templates below: category UTILITY; language en; status DRAFT. Submit each
in Meta Business Manager and replace the names/language codes if needed. Parameter
order is the order shown. Staff alerts also require consent and approved templates.

earlydryer_job_received
-----------------------

{{1}}: Order {{2}} received: {{3}} items. Promised {{4}}. Amount {{5}}; balance {{6}}. Call {{7}}.

Parameters: plant, number, items, promised, amount, balance, plant_phone.

earlydryer_job_ready
--------------------

{{1}}: Order {{2}} ready. Collect at shelf {{3}}. Hours: {{4}}. Balance {{5}}. Call {{6}}.

Parameters: plant, number, shelf, hours, balance, plant_phone.

earlydryer_job_out_for_delivery
-------------------------------

{{1}}: Order {{2}} is out for delivery. Balance {{3}}. Call {{4}}.

Parameters: plant, number, balance, plant_phone.

earlydryer_job_delivered
------------------------

{{1}}: Order {{2}} delivered. Thank you. Call {{3}}.

Parameters: plant, number, plant_phone.

earlydryer_job_collected
------------------------

{{1}}: Thank you for collecting {{2}}. Call {{3}}.

Parameters: plant, number, plant_phone.

earlydryer_payment_received
---------------------------

{{1}}: Payment {{2}} received: {{3}}. Thank you. Call {{4}}.

Parameters: plant, number, amount, plant_phone.

earlydryer_uncollected_reminder
-------------------------------

{{1}}: Please collect {{2}}. {{3}} days before the 14-day limit. Balance {{4}}. Call {{5}}.

Parameters: plant, number, days_left, balance, plant_phone.

earlydryer_job_uncollected
--------------------------

{{1}}: Order {{2}} remains uncollected after 14 days. Please contact us. Call {{3}}.

Parameters: plant, number, plant_phone.

earlydryer_wallet_topup
-----------------------

{{1}}: Wallet top-up {{2}}. New balance {{3}}. Call {{4}}.

Parameters: plant, amount, wallet_balance, plant_phone.

earlydryer_wallet_spend
-----------------------

{{1}}: Wallet payment {{2}}. New balance {{3}}. Call {{4}}.

Parameters: plant, amount, wallet_balance, plant_phone.

earlydryer_pickup_booked
------------------------

{{1}}: Pickup booking {{2}}: {{3}}. Call {{4}}.

Parameters: plant, number, summary, plant_phone.

earlydryer_pickup_done
----------------------

{{1}}: Pickup {{2}} completed. {{3}}. Call {{4}}.

Parameters: plant, number, summary, plant_phone.

earlydryer_complaint_update
---------------------------

{{1}}: Update on {{2}}: {{3}}. Call {{4}}.

Parameters: plant, number, summary, plant_phone.

earlydryer_alert_overdue
------------------------

{{1}}: Overdue orders: {{2}}. Call {{3}}.

Parameters: plant, summary, plant_phone.

earlydryer_alert_large_discount
-------------------------------

{{1}}: Discount alert {{2}}: {{3}}. Call {{4}}.

Parameters: plant, number, summary, plant_phone.

earlydryer_alert_unpaid_release
-------------------------------

{{1}}: Unpaid release or credit {{2}}: {{3}}. Call {{4}}.

Parameters: plant, number, summary, plant_phone.

earlydryer_alert_scan_mismatch
------------------------------

{{1}}: Scan mismatch {{2}}: {{3}}. Call {{4}}.

Parameters: plant, number, summary, plant_phone.

earlydryer_alert_damage_found
-----------------------------

{{1}}: Damage found {{2}}: {{3}}. Call {{4}}.

Parameters: plant, number, summary, plant_phone.

earlydryer_alert_wallet_overdraw
--------------------------------

{{1}}: Wallet overdraw {{2}}: {{3}}. Call {{4}}.

Parameters: plant, number, summary, plant_phone.

earlydryer_alert_job_creation_failed
------------------------------------

{{1}}: POS job creation failed {{2}}: {{3}}. Call {{4}}.

Parameters: plant, number, summary, plant_phone.

earlydryer_alert_failed_delivery
--------------------------------

{{1}}: Delivery failed {{2}}: {{3}}. Call {{4}}.

Parameters: plant, number, summary, plant_phone.

earlydryer_eod_report
---------------------

{{1}}: Daily report: {{2}}. Call {{3}}.

Parameters: plant, summary, plant_phone.

