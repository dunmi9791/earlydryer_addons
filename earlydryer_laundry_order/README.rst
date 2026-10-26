=========================
Earlydryer Laundry Orders
=========================

The **laundry job** (``laundry.job``) carries every Earlydryer customer order
through the plant, from drop-off to collection or delivery: one job per order,
one item (``laundry.job.item``) per garment piece, one stage-log row
(``laundry.job.stage.log``) per stage move. The commercial record stays a
``sale.order`` (pickups, website, WhatsApp, phone, corporate) or a
``pos.order`` (walk-ins, set by ``earlydryer_pos``); the job carries
operations only.

Depends on ``earlydryer_base`` (plants, roles, branch security, approvals) and
``earlydryer_service_catalog`` (garments, services, prices, turnaround).

**Table of contents**

.. contents::
   :local:

Job lifecycle
=============

::

    Received → Tagged → Sorted → Washed → Dried → Ironed → QC → Packed → Ready
                                                                          ├→ Collected
                                                                          ├→ Out for Delivery → Delivered
                                                                          └→ Uncollected (day 14, automatic)
    Cancelled (Branch Manager, any non-closed stage)

* **Creation.** Confirming a sales order with laundry lines creates its job
  (once). Each unit of quantity becomes ``piece_count`` items (a 3-piece
  agbada gives pieces 1/3, 2/3, 3/3). Price, surcharges, colour and condition
  are copied from the order line; the price at intake is final. The garment
  price is carried by piece 1 so the items add up to the order lines.
  Numbering per plant: ``<CODE>/<YY>/<00001>``, restarting every year.
* **Promised date** comes from ``earlydryer.catalog.promised_datetime`` while
  the job is Received (items or express change → recomputed). Afterwards only
  a Branch Manager can change it.
* **Stage moves** record the employee who did the work (``hr.employee``, may
  have no login; required for Sorted … Packed) and the user who recorded it.
  The normal path skips the stages none of the items' services need
  (*Washing / Drying / Ironing Stage* flags on the service type). Going
  backwards or skipping a needed stage: Branch Manager, with a note.
* **Gates.** Tagged: ``_check_can_tag()`` (always true here). Packed: every
  item passed QC, none missing. Ready: a shelf of the job's plant. Collected
  and Out for Delivery: the release check.
* **QC.** *Quality Check* passes items, or fails some of them: they get
  *Rework*, their rework count increases and the job goes back to Sorted,
  Washed or Ironed (logged with the reason). Items already passed stay passed.
* **Release check — nothing leaves the plant unpaid.** When the job's amount
  due is above zero, a *credit* approval is needed (approval engine of
  ``earlydryer_base``). *Request Credit Approval* opens the approval wizard
  with the amount due; once a manager approves an amount at or above the due,
  the job can leave. Branch Managers self-approve (rule shipped with
  *self approve*). If no rule matches (rule archived), a Branch Manager is
  still required.
* **Amounts** (not stored: they follow invoices and payments):

  * sales order: total of the order (garments, surcharges, express, retail);
    paid = settled part of its posted customer invoices (refunds deducted)
    + ``_earlydryer_extra_paid()``;
  * POS order: ``_earlydryer_pos_amounts()``, see below;
  * manual job: nothing due.

* **Items are locked after Received** except tag, QC result, missing flag,
  condition note, photos and order. A Branch Manager can still correct them by
  filling *Correction reason* above the items (logged in the chatter). Prices
  are read-only below Branch Manager.
* **Customer requests.** *Customer Asked to Change / to Cancel* (Front Desk,
  Customer Service) schedule a To Do for the plant's manager (fallback: the
  Branch Managers allowed on the plant) and log the request. The manager then
  edits or cancels. Cancelling never touches the order, invoices or payments:
  a note is posted on the source order and Finance decides on refunds.
* **Uncollected orders.** A daily cron reminds customers of Ready jobs to
  collect on the reminder days (default 3, 7, 12 days after Ready; each day
  once, a missed run only sends the latest) and moves them to *Uncollected* on
  day 14 (Earlydryer's liability ends). A Branch Manager can still mark an
  uncollected job Collected, with a note. Settings: *Earlydryer >
  Configuration > Laundry Settings* (``earlydryer.uncollected_days``,
  ``earlydryer.uncollected_reminder_days``).

Stage-move API
==============

One method does every move; buttons, wizards and later modules (scan board,
POS sync, API, logistics) all call it::

    jobs.action_move_to(
        "washed",                 # target state
        employee=employee,        # hr.employee record or id (who did the work)
        items=items,              # laundry.job.item records/ids covered; empty = whole job
        note="...",               # required backwards, on skips and cancellations
    )

* works on several jobs at once; validates every job before moving any;
* calling it twice with the same target does nothing the second time (no
  duplicate log row);
* raises ``UserError``/``AccessError`` with a message for the front desk;
* after each move: ``ready_on``/``closed_on``, one log row, a chatter note,
  then the hook ``_earlydryer_on_state_changed(old_state, new_state)``.

QC: ``job.action_qc_pass(items=None, employee=emp)`` and
``job.action_qc_fail(items, emp, "washed", "Collar stain")``.

Hooks for later modules
=======================

``_check_can_tag()`` — earlydryer_tagging::

    def _check_can_tag(self):
        untagged = self.item_ids.filtered(
            lambda i: i.service_type_id.requires_tag and not i.tag_code
        )
        return super()._check_can_tag() and not untagged

``_earlydryer_on_state_changed(old_state, new_state)`` — notifications,
logistics::

    def _earlydryer_on_state_changed(self, old_state, new_state):
        res = super()._earlydryer_on_state_changed(old_state, new_state)
        if new_state == "ready":
            self._send_whatsapp("order_ready")
        return res

``_earlydryer_send_uncollected_reminder(day)`` — called once per reminder
day (logs a chatter note here)::

    def _earlydryer_send_uncollected_reminder(self, day):
        super()._earlydryer_send_uncollected_reminder(day)
        self._send_whatsapp("collect_reminder", day=day)

``_earlydryer_pos_amounts()`` — returns ``{"total", "paid"}``. Here a paid or
posted POS order is fully paid, except the part paid with a *Customer
Account* method (Odoo 19: a payment method without journal, ``type ==
"pay_later"``), which stays due until the order's invoice is paid; a draft
order counts its other payments. earlydryer_pos refines it::

    def _earlydryer_pos_amounts(self):
        amounts = super()._earlydryer_pos_amounts()
        amounts["paid"] += self._offline_payments_not_synced()
        return amounts

``_earlydryer_extra_paid()`` — amounts paid outside the source record
(earlydryer_wallet advance payments)::

    def _earlydryer_extra_paid(self):
        return super()._earlydryer_extra_paid() + self._wallet_reserved_amount()

``_earlydryer_create_from_lines(partner, branch, channel, fulfilment,
express, lines, source=None, **extra)`` — creates the job of an order,
idempotent per source (returns the existing job), independent of the sale
model. ``earlydryer_pos`` calls it when an offline order syncs::

    job = env["laundry.job"].sudo()._earlydryer_create_from_lines(
        order.partner_id, order.config_id.earlydryer_branch_id,
        "walk_in", "collect", express,
        [{"product_id": line.product_id.id, "quantity": line.qty,
          "price_unit": line.price_unit, "surcharge_ids": surcharge_ids,
          "colour": "Navy", "condition_note": "", "source_line_id": line.id}
         for line in garment_lines],
        source=order,
    )

``source=None`` creates a *manual* job (Branch Manager and above: corrections
and migration of open orders from the old system).

Also available: ``_earlydryer_manual_amounts()`` (amounts of manual jobs),
``_earlydryer_check_release()``, ``_earlydryer_next_state()``,
``_earlydryer_catalog_channel(channel)`` (job channel → catalogue price-list
channel: website, WhatsApp and phone are priced as *pickup*).

Sales orders
============

Quotations get a *Laundry* section: plant (defaults to the user's, required
when the order has laundry lines), channel, fulfilment, express. Changing the
plant, channel or customer of a draft order proposes the Earlydryer price list
(``_earlydryer_resolve_pricelist``). Garment lines get surcharges, colour and
condition; the ``+`` button of a line (or *Price Surcharges/Express* in the
header) (re)creates its surcharge and express lines with
``earlydryer.catalog.price_item``, linked by ``earlydryer_parent_line_id``.

Security
========

+---------------------------+----------------+----------------+-------------+
| Group                     | Jobs           | Items          | Stage log   |
+===========================+================+================+=============+
| Front Desk                | read, create,  | read, create,  | read,       |
|                           | write          | write          | create      |
+---------------------------+----------------+----------------+-------------+
| Production Staff, QC      | read, write    | read, write    | read,       |
|                           | (moves)        |                | create      |
+---------------------------+----------------+----------------+-------------+
| Rider                     | read           | read           | read        |
+---------------------------+----------------+----------------+-------------+
| Customer Service          | read, write    | read           | read        |
+---------------------------+----------------+----------------+-------------+
| Branch Manager and above  | read, create,  | full           | read,       |
|                           | write          |                | create      |
+---------------------------+----------------+----------------+-------------+
| Finance                   | read           | read           | read        |
+---------------------------+----------------+----------------+-------------+
| Earlydryer Administrator  | full           | full           | full        |
+---------------------------+----------------+----------------+-------------+

* Record rules follow the base branch pattern: own plants, every plant with
  ``group_all_branches`` (Operations Manager, Finance, HR, Management).
* Enforced in Python: ``state`` only through ``action_move_to``; manual jobs,
  backward moves, skips, cancellations, item prices, the promised date after
  intake and the shelf after collection need a Branch Manager; nobody but the
  Earlydryer Administrator deletes jobs or edits/deletes log rows.
* OCA ``auditlog`` rules on jobs and items (write, unlink), confirmed by the
  ``post_init_hook``.
* Front Desk and Customer Service now also imply *Sales / User: All
  Documents*: they take pickup, phone and WhatsApp orders as quotations.

Odoo 19 notes and deviations
============================

* **Sale confirmation**: ``action_confirm`` checks the plant, the job is
  created in ``_action_confirm`` (runs in the ``sale`` state, also for
  website/portal confirmations), with sudo.
* **POS customer account**: there is no ``invoiced`` POS state in 19
  (``draft/paid/done/cancel``) and no ``is_pay_later`` flag; a *Customer
  Account* method is a payment method without journal (computed ``type ==
  "pay_later"``). Uninvoiced pay-later orders stay due until earlydryer_pos
  links them to their receivable.
* **Sequences**: ``use_date_range`` is in core 19 (no extra module): yearly
  sub-sequences with prefix ``<CODE>/%(range_y)s/``. A plant code change
  updates the prefix.
* **Employee picker**: users without HR rights read employees through
  ``hr.employee.public``; ``earlydryer_branch_id`` is added there too so the
  picker can be filtered by plant.
* ``ir.actions.act_window`` has no ``inline`` target in 19 (settings action
  opens in the main window).
* ``is_overdue`` also excludes Ready and Out for Delivery jobs (the plant's
  work is done; a ready order past its promise is not late).
* ``promised_on`` is a stored computed field computed only while Received; it
  is settled before a job leaves Received.
* Stage skips use three booleans on the service type (``uses_wash``,
  ``uses_dry``, ``uses_iron``) rather than a stage model: only these three
  stages can be left out, and booleans are simpler to configure and to load
  in the offline POS. Shipped placeholders (set once at install): ironing
  only skips washing and drying; wash & fold, shoes, bags and rugs skip
  ironing.
* Every move posts one chatter note (stage + employee + note); the stage
  change itself is also tracked.

Known issues / Open questions for Earlydryer
============================================

* **Who records the employee for each stage?** Front desk for everyone, or
  each station (tablet, scan board)? The design works both ways: the employee
  and the recording user are separate fields.
* **Who approves credit and from what amount?** Shipped rule (``noupdate``):
  credit on laundry jobs, any amount above 0, Branch Manager, self-approval
  on. Adjust it in *Earlydryer > Configuration > Approval Rules*.
* **Which services skip which stages?** Placeholders above.
* **Reminder schedule before day 14**: 3, 7 and 12 days by default; confirm
  days, wording and channel (WhatsApp/SMS in earlydryer_notifications).
* **Migration**: will open orders from the old system be loaded as manual
  jobs (Branch Manager)?
* Should cancelling a sales order cancel its job (not done here)?
* Sales order record rules are not restricted per plant (Sales "All
  Documents" rights see every order); jobs are.
* Amounts assume invoices in the company currency.

Credits
=======

Authors
-------

* Secteur
