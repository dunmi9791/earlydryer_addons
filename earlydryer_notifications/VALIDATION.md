# Validation and delivery

Implemented only `earlydryer_notifications` on `feat/earlydryer-notifications`.
No changes to the earlier add-ons, no push, no merge, no production configuration
edits, and no real provider requests or SMTP deliveries.

## Module tree

```text
earlydryer_notifications/
├── __init__.py, __manifest__.py, hooks.py, tools.py
├── models/                 # 17 model/extension files, one model per file
│   ├── notify_provider.py, notify_event.py, notify_template.py
│   ├── notify_message.py, notify_inbound.py, notify_webhook_log.py
│   ├── notify_alert_rule.py, notify_alert.py, notify_eod_report.py
│   ├── laundry_job.py, pos_order.py, account_payment.py
│   ├── earlydryer_wallet_transaction.py, earlydryer_approval_request.py
│   └── earlydryer_branch.py, res_partner.py, res_config_settings.py
├── providers/              # plain adapters and result/event dataclasses
├── controllers/webhook.py
├── wizards/                # reply/test-send and dated EOD resend
├── security/               # ACLs, company/branch rules, technical webhook user
├── data/                   # 22 events, 44 templates, alerts, queue jobs, crons, audit
├── demo/notifications.xml
├── views/                  # inbox/outbox/configuration and inherited forms
├── static/src/             # POS consent, including offline quick-create
├── tests/                  # sending/bot/security, financial hooks, HTTP webhooks
├── README.rst              # setup, policies, provider examples, Meta submission list
└── VALIDATION.md
```

## Environment and executed checks

The requested WSL container `earlydryer` and `/home/dominic/...` config do not
exist in this cloud machine. Used the already prepared cloud Odoo 19.0-20261015
and PostgreSQL 16 instead, with pinned OCA 19.0 sources. The existing development
database was left intact. Only newly created databases named
`earlydryer_notify_test` and `earlydryer_notify_demo` were used for these checks.

Executed cloud commands (runner helper at `/workspace/.earlydryer/notify-run.sh`
wraps the official Odoo image with the existing config/add-ons/dependency mounts):

```sh
# Fresh no-demo installation: succeeded.
/workspace/.earlydryer/notify-run.sh -d earlydryer_notify_test \
  -i earlydryer_notifications --without-demo=True --stop-after-init

# Fresh installation including all dependency and notification demo data:
# succeeded, no warnings.
/workspace/.earlydryer/notify-run.sh -d earlydryer_notify_demo \
  -i earlydryer_notifications --without-demo=False --stop-after-init

# Demo database: 56 tests, zero failures/errors/warnings.
/workspace/.earlydryer/notify-run.sh -d earlydryer_notify_demo \
  -u earlydryer_notifications --test-enable \
  --test-tags /earlydryer_notifications --stop-after-init

# Recreated the throwaway no-demo database, including optional Production:
# installation succeeded. A new scan-hook test exposed a missing write_date
# assumption; the implementation was corrected and the complete suite rerun.
/workspace/.earlydryer/notify-run.sh -d earlydryer_notify_test \
  -i earlydryer_notifications,earlydryer_production --without-demo=True \
  --test-enable --test-tags /earlydryer_notifications --stop-after-init

# Final complete run: 60 tests, zero failures/errors/warnings, exit 0.
/workspace/.earlydryer/notify-run.sh -d earlydryer_notify_test \
  -u earlydryer_notifications --test-enable \
  --test-tags /earlydryer_notifications --stop-after-init
```

Use Odoo's result line: **0 failed, 0 error(s) of 60 tests**. Its separate stats
line reports 66 because it includes suite setup/teardown accounting. The earlier
demo run preceded four additional regression tests; final coverage includes the
optional damage hook, real scan-log hook, staff employee-mobile fallback and
cross-plant extra-phone exclusion.

All provider HTTP calls in tests are mocked; other tests use log-only adapters.
Queue tests use `trap_jobs`, including synchronous execution of trapped work.

Static checks:

```sh
ruff format --check earlydryer_notifications
ruff check earlydryer_notifications --select E4,E7,E9,F,I \
  --per-file-ignores '**/__init__.py:F401'
pylint --load-plugins=pylint_odoo --disable=all --enable=odoolint \
  --manifest-required-authors=Secteur earlydryer_notifications
git diff --check
```

Ruff passes. Odoo-specific pylint checks pass, rating 10.00/10. Secteur is the
required manifest author from the prompt. OCA pre-commit is not configured in
this repository; it was not claimed as executed.

## Live queue and functional smoke

A temporary cloud server `earlydryer-notify-smoke` was started on the demo
throwaway database with:

```text
--load=base,web,queue_job --workers=2 --max-cron-threads=0
ODOO_QUEUE_JOB_HOST=127.0.0.1
ODOO_QUEUE_JOB_CHANNELS=root:2,root.earlydryer_notify:1
```

The runner logged `queue job runner ready for db earlydryer_notify_demo`.
Its default destination inherited `0.0.0.0` from the HTTP listener and received
403 in this environment; selecting the actual loopback host fixed it. The
runner then recovered the unexecuted job and completed it. README contains
reviewable deployment configuration lines; production config was not edited.

Verified against the running worker:

* HTTP login form responds successfully.
* `curl` POST of a sample Meta `status` payload, signed using the clearly labelled
  demo-only app secret: HTTP 200; webhook processing job completed; inbound became
  `auto_replied`; bot reply became `sent` through the log-only provider.
* Replaying the same inbound ID did not create duplicate inbound/bot replies.
* Created a demo sale/job and moved it through actual stages to Ready; received
  and ready messages were sent, with a chatter note and shelf details.
* Posted a wallet top-up and its payment; both corresponding messages were sent.
* Called overdue-digest and EOD methods. The scheduled EOD delivery completed and
  its WhatsApp summary reached sent through the log-only provider.
* Worker states for webhook, message, alert and EOD jobs were `done`.

The test-only EOD email recipient list was cleared for the live smoke so no SMTP
was attempted. Automated tests separately verify that PDF rendering is requested,
the resulting attachment is linked, and email is queued. No Meta/BSP/SMS
credentials were supplied, so no real test message was sent. No browser automation
capability was available: HTTP/ORM checks and asset generation were executed;
visual POS/inbox browser checks remain for the operator's deployment.

## Intentional differences and operational decisions

* Official Meta documentation requests were blocked by the environment proxy
  (CONNECT 403). Consequently `graph_version` has no guessed default; an explicit
  supported version is required for Meta providers. README links the official
  messages/webhooks/changelog documentation for review before real activation.
* Retries use successor queue jobs for normal provider failures so attempt/rate
  counters and error details commit. Raising `RetryableJobError` in that same
  transaction would roll those changes back. Queue function retry patterns are
  also registered for processing/runner retry support.
* Narrow elevated reads authenticate the public webhook's provider/token/HMAC.
  Public users receive no model ACLs. Receipt creation runs as the dedicated
  technical user; processing and outbound work elevate inside private jobs.
* Actual hooks/fields include `earlydryer_released_unpaid`,
  `_earlydryer_after_sync`, and the existing accounting QWeb daily-cash action.
  Production is optional and was tested without adding it to dependencies.
* Reused `earlydryer_wallet.tools.normalize_ng_phone`; POS reuses its existing
  JavaScript normalizer. Different runtimes require both; earlier modules were
  not changed to move their helpers.
* Existing contacts are not retroactively opted in. New intake defaults on;
  STOP/START is retained as phone-level consent metadata, including an unknown
  phone that is matched to a contact later. Offline matching never clears STOP.
* Meta 131026 means undeliverable and can have causes besides WhatsApp absence;
  it flags the number unavailable for fallback. No claim of verified membership
  is made. Real template approval and utility categorization belong to Meta/BSP.
* Provider secret/header/body fields are excluded from audit values, rather
  than retaining masked secret snapshots. Bodies copied to job chatter are
  also removed by retention. Metadata and cost/count records are retained.
* EOD completion/receipt/posted payment figures are date-scoped; ready/overdue
  counts are the current backlog snapshot. WhatsApp PDF upload was omitted.
* Generic gateways use an explicit signed canonical inbound/status contract;
  gateway-specific callback remapping must be configured by the operator.

Provider choices, sender ID, consent wording, final texts/template approver,
quiet hours, manager thresholds/channels, EOD recipients/time, collected-message
preference and retention decisions are listed in README. Those decisions and
credentials are needed before real sending, not for the tested log-only workflow.

## Cleanup

The temporary queue server was stopped and removed. Both throwaway databases
and their filestores were removed after validation. The existing cloud development
application/database and repository dependencies were preserved.
