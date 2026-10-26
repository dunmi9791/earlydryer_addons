==============
Earlydryer POS
==============

The plant counter of Earlydryer on the Odoo 19 Community Point of Sale:
laundry **intake** (customer, garments, surcharges, express, condition notes
and photos, tags, payment in full or partly on the customer's account),
**retail** sales from the plant's stock, and **collection** (scan the receipt
or a tag, see the shelf, release only when paid). Intake, payment, tag and
receipt printing, and collection of the jobs cached on the till keep working
**offline**. Laundry jobs are created on the server when the order syncs,
never in the browser.

Depends on ``earlydryer_tagging`` (and through it ``earlydryer_laundry_order``,
``earlydryer_service_catalog``, ``earlydryer_base``), ``point_of_sale``,
``pos_hr`` and OCA ``queue_job``.

**Table of contents**

.. contents::
   :local:

Setting up a till
=================

1. **Plant**: *Point of Sale > Configuration > Settings*, block *Earlydryer*:
   choose the plant and tick *Laundry Counter*. A laundry counter needs:

   * a default **price list of its plant**: use *Sync POS Price Lists* on the
     plant (walk-in list as default, corporate contract lists available, so
     contract customers are priced offline too);
   * a **Customer Account** payment method: a method *without journal*
     (Odoo 19 type ``pay_later``) with *Identify Customer* ticked
     (``split_transactions``). Without *Identify Customer* the session would
     post one anonymous receivable line and balances could not be followed per
     customer, so the till refuses to be enabled without it.

2. **Payment methods**: cash (cash journal of the plant), card terminal (a bank
   journal; a terminal provider can be added later), bank transfer (a plain
   bank-journal method: the customer transferred to Earlydryer's account and
   the cashier confirms receipt), customer account (above).
3. **Walk-in customer**: the anonymous contact used for retail-only sales.
   Laundry always needs a real customer (name and phone), never this one.
4. **Employees** (``pos_hr``): log in with the employee PIN. Tick *Restrict
   Price Modifications to Managers* (core): Front Desk employees then cannot
   change prices (the *Price* key is disabled and price changes are refused,
   laundry lines included). Managers' PINs approve discounts and credit.
5. **Tag ranges** (printed-tag plants): the till holds blocks of tag numbers
   taken from the plant's tag sequence (*Tag Range Size*, default 500). A new
   block is allocated when fewer than *Top up below* % (default 20) are left:
   at session opening and whenever the till is online. Pre-printed plants need
   no range.
6. **Labels**: *Label (mm)* (default 50 × 25) is the garment tag size for
   printing from the browser. Set the PC's label printer as the browser's
   printer for the tag print dialog (Chrome kiosk printing avoids the dialog).
   *Print after Payment* prints the tags automatically.
7. **Receipt printer**: an Epson ePOS network printer is configured in core
   (*Connected Devices*; ePOS is part of ``point_of_sale`` in 19, there is no
   ``pos_epson_printer`` module any more). Receipts print there as usual;
   garment tags always print through the browser.
8. **Receipt terms** (placeholder wording) and *Collection Cache (days)*.

Intake
======

On a laundry counter the product screen opens on the **Laundry** tab
(*Retail* shows the normal product grid and search):

1. **Customer** first: search by phone or name (on the till, then on the
   server when online), or *New Customer* with a name and a phone; Nigerian
   numbers are normalised (``0803 123 4567`` → ``+2348031234567``). Online the
   contact is created at once; offline it is kept on the order and matched by
   phone or created when the order syncs. The walk-in customer is refused for
   laundry.
2. **Garment, then service**: big buttons per garment category (with its
   image); a category shows its services with their price from the current
   price list (the POS price list engine, offline).
3. **Garment details** open after each garment (tap the selected line again,
   or *Details*, to reopen): surcharge chips allowed for the category and
   service, colour swatches or text, brand, condition chips (stain, tear,
   missing button, faded...), **photos**, and in pre-printed plants one tag
   field per piece (scan them in turn; Enter moves to the next).
4. **Order options**: *Express* (adds an express line to each garment whose
   service allows it), collect or delivery, customer instructions, and an
   order-wide discount.
5. **Promised time**: estimated on the till from the latest turnaround of the
   garments, counted in the plant's working hours (resource calendar and
   public holidays loaded with the session). The receipt says "estimated"; the
   laundry job computes its own promise from the intake time when it syncs.

Linked lines
------------

Surcharges and express are separate lines on their own products (as in the
catalogue), linked to the garment line by ``earlydryer_parent_line_uuid``; the
server resolves ``earlydryer_parent_line_id``. Fixed surcharges are priced
through the price list, percentage surcharges and express with the formulas
of ``earlydryer.catalog.price_item``. Deleting a garment deletes its linked
lines, changing its quantity changes theirs, a garment discount applies to
them; linked lines cannot be edited or removed on their own.

**Quantity**: "5 shirts, wash & iron" is one line of quantity 5: 5 job items
and 5 tags (× pieces for multi-piece garments). The details apply to all units;
split the line when one garment differs.

Discounts and manager PIN
-------------------------

Discount rules come from ``earlydryer.approval.rule`` (type *Discount*, model
``pos.order``, the plant's or all plants), loaded with the session. The
server computes, for each ``pos_hr`` employee, the rules their user's groups
may approve (``_earlydryer_rule_ids``); PINs stay the hashes pos_hr already
loads. When a discount (line or order) matches a rule:

* the cashier's own rule with *self-approve*: applied at once;
* otherwise a manager PIN is asked; only an employee whose rule list covers
  the rule is accepted. The discount is applied only after a valid PIN.

The approver and rule are stored on the lines. At sync the server creates an
**approved** ``earlydryer.approval.request`` on the POS order (decided by the
approver employee's user, value = the discount %) and a *Till PIN Approval*
log (employee, user, cashier, till, time). No matching rule: core behaviour.
On a laundry counter discounts are always typed in a popup (one value, one
approval) rather than key by key. Only employees of the till's plant (or
without a plant) are offered as approvers. Rules, employees and PINs are
loaded when the session opens (core keeps them in IndexedDB while the session
is open), so a rule change applies to a till from its next session.

Payment and tags
================

Core payment methods. Partial payment = split: e.g. ₦5,000 cash and the rest
on *Customer Account*. A balance on account needs an identified customer: the
till refuses the walk-in or no customer (core only checks a customer is set
when the method identifies customers).

On validation, before printing:

* **printed tags**: the next numbers of the till's ranges, with the plant
  prefix, 7 digits and the Luhn check digit (``core/tag_code.js``, a port of
  the tagging helper with the same test vectors). The next number is stored
  in ``localStorage`` before anything prints and is recomputed at start-up as
  the highest of the server's, the stored one and the codes on the orders kept
  in IndexedDB, so a reload never reuses a number. Without numbers left the
  garments are printed "TO TAG AT THE COUNTER" and the job is tagged from the
  backend or the tagging screen.
* **pre-printed tags**: the codes scanned in the details, checked against the
  plant's pattern and for duplicates within the order. Uniqueness among open
  jobs is checked on the server.

The **receipt** of a laundry order adds the plant name, address and phone,
the order reference as a Code128 barcode (rendered in the browser), the
customer, each garment with its surcharges, express, tags and condition, the
estimated promise, amount paid, balance due and the terms. Retail-only orders
keep the normal receipt.

**Tag labels** (one per piece: barcode, code, order reference, customer short
name, garment, service, piece x/n, EXPRESS, promised date) are rendered in a
hidden iframe sized to the label and printed with the browser, offline too.
*Reprint Tags* is on the receipt screen and in the order list.

Condition photos
================

``<input type="file" accept="image/*" capture="environment">`` (tablet camera
or webcam). Pictures are resized in the browser (longest side 1280 px, JPEG
0.7, about 150 KB) and kept in the till's own IndexedDB
(``earlydryer_pos_<config id>``, store ``photos``), never in the order payload.
Once the order is synced, each photo is sent with
``pos.order.earlydryer_upload_photo(order_uuid, line_uuid, index, data)``: the
server attaches it to every job item of that line (``photo_ids``), once per
(order, line, index) (``earlydryer.pos.photo``). Uploads retry with backoff;
a photo is deleted locally only when the server confirmed it. The header
shows the photos waiting, and closing the session warns while some remain.

Job creation on sync
====================

``pos.order._process_saved_order`` (called by ``sync_from_ui`` for new and
updated orders): for a paid order of a laundry counter with garment lines, in
a **savepoint**:

1. plain line dicts for ``laundry.job._earlydryer_create_from_lines``
   (price after discount, surcharges from the linked lines, colour, brand,
   condition, ``source_line_id``), partner, plant, channel ``walk_in``,
   fulfilment, express, ``received_on`` = the order date (offline orders keep
   their intake time; the promise is computed from it);
2. the tag codes are written on the items: tagging validates them and
   consumes the till's range. A refused code (pre-printed tag on an open job,
   code never issued...) leaves that item untagged with a *Tag Conflict*
   note, a chatter note and an activity for the branch manager; the job is
   created anyway. Jobs whose items are all tagged move to *Tagged*;
3. ``earlydryer_job_id`` is linked and the discount approvals are logged.

On any error the savepoint is rolled back, the sale is kept, the error is
stored in ``earlydryer_job_error``, the branch manager gets an activity and a
``queue_job`` retries ``_earlydryer_create_job_from_pos`` (idempotent, like the
job creation). *Retry Job Creation* on the order does the same; *Orders >
POS Orders without Job* lists them.

Collection
==========

*Collect* in the header: scan the receipt barcode or a tag, or type a phone,
name or job number. Online the server answers
(``laundry.job.earlydryer_pos_lookup`` uses the tagging scan API, plus
``earlydryer_pos_collection_info``); offline the session's collection cache
is searched. The card shows customer, items, tags, the **shelf in large
type**, stage and amount due.

* Not ready (before *Ready*): the stage and promise, no release.
* Paid (nothing due, or an approved credit): *Release*.
* Balance due: *Take payment* (a *Balance Settlement* line for the due amount
  on a new order, then payment; the release is recorded when the payment is
  validated), or *Manager approves credit* (PIN of an employee who may approve
  the laundry job credit rule; without such rule, a Branch Manager).

A release is a queued **collection record** (uuid, job, employee, mode,
approver, amount seen, time), kept in IndexedDB and sent with
``earlydryer.pos.collection.earlydryer_pos_submit`` when online (after the
till's orders, so a settlement is on the server first; idempotent per uuid).
The server runs the release rule (``_earlydryer_check_release``) as the
approving manager for a credit, else as the collecting employee's user, then
moves the job to *Collected* with the employee and a stage note. If the
server finds the job unpaid (stale cache), the collection is still recorded,
the job is flagged **Released Unpaid** and the branch manager gets an
activity: what happened at the counter is never reversed. A manager credit
creates an approved *Credit* request on the job for the amount, and a PIN log.

The collection cache (ready, packed, out-for-delivery and uncollected jobs of
the plant changed in the last *Collection Cache (days)*, at most 2,000) is
loaded with the session and refreshed when the till comes back online and at
most every 2 minutes after syncs. Jobs released on this till are removed from
it at once, so they cannot be released twice offline.

Settlement accounting
=====================

Odoo 19 Community has no supported "pay a customer's balance" at the POS
(``pos_settle_due`` is Enterprise). This module:

* adds the service product **Balance Settlement**
  (``earlydryer_kind = settlement``, no tax);
* at session closing, its sales lines are grouped per customer and posted to
  the **customer's receivable account** with the partner (``pos.session``
  ``_get_sale_key`` / ``_get_sale_vals``), not to revenue, flagged
  ``earlydryer_settlement`` on the journal item;
* after the closing entry is posted, each settlement credit is reconciled
  with the open receivable of the jobs it pays (pay-later lines of their POS
  order's session entry, or its invoice), then with the customer's other open
  receivables, oldest first.

Customer-account amounts
------------------------

``laundry.job._earlydryer_pos_amounts()``: total = the POS order without its
settlement lines; due = the part paid with Customer Account still open on the
receivable — the invoice residual when the order is invoiced, otherwise the
residual of the customer's pay-later lines in the session entry, allocated to
the customer's orders of that session oldest first; before the session is
closed, the whole pay-later amount — less settlements taken at a till whose
session is not closed yet. Payments Finance reconciles outside the POS lower
the due amount.

Offline: how and its limits
===========================

* Core POS keeps orders in IndexedDB and syncs them when online; the session
  data (catalogue, price lists, surcharges, rules, employees, tag ranges,
  calendar, collection cache) is cached by the POS and, for the refreshed
  parts, in the till's own IndexedDB.
* New customers created offline have no history and no other till knows them
  until the order syncs; they are matched by phone at sync.
* Collection offline only finds jobs in the cache, with the amounts known at
  the last refresh (the server re-checks; see *Released Unpaid*). Customers
  not loaded on the till cannot pay a balance offline (use manager credit).
* Without tag numbers left, garments are tagged at the counter later.
* Photos and collections wait on the device: do not clear the browser data of
  a till with pending uploads.

Manual offline test (tours cannot run in the official image, see below):
open a session as a Front Desk employee, set the browser offline in the
developer tools (Network: Offline), take two intakes and a collection from
the cache, reload the page (still offline: everything is there and no tag
number repeats), go back online and check the orders, jobs (intake times),
photos and the collection on the server.

Security
========

* Front Desk staff use the till as ``pos_hr`` employees; Branch Manager and
  above are POS managers (``earlydryer_base``).
* ``pos.config`` follows the branch pattern (tills without a plant stay
  visible); photos, collections and PIN logs too.
* Photo upload and collection RPCs check the user works on the plant of the
  order or job and that a session of that plant is open.
* Every manager PIN is logged (*Orders > Till PIN Approvals*).
* ``auditlog`` (fast mode) on ``pos.order.line`` writes and deletes: price and
  discount changes made after the sale.

Barcode library
===============

``static/lib/jsbarcode/JsBarcode.code128.min.js``: **JsBarcode 3.11.6**
(Code128 build), © Johan Lindell, **MIT** licence (``LICENSE`` next to it).
Barcodes are rendered in the browser because ``/report/barcode`` needs the
server.

Odoo 19 notes and deviations
============================

* **Loading**: models load through ``pos.load.mixin``
  (``_load_pos_data_models`` / ``_domain`` / ``_fields`` / ``_read``). The
  garment categories (with their image as a data URL), service types,
  surcharges and the discount/credit approval rules are loaded as POS models;
  the volatile data (tag ranges, plant, calendar, collection cache) rides on
  the ``pos.config`` record as ``_earlydryer`` (keys starting with ``_`` are
  kept by the 19 JS models) and is refreshed by
  ``pos.config.earlydryer_pos_refresh``. Fields listed in
  ``_load_pos_data_fields`` travel both ways (``pos.order`` loads all its
  fields in 19; ``pos.order.line`` has an explicit list, extended here).
* **Sync hook**: ``_process_saved_order`` (19 has no ``_process_order`` hook
  after creation for both new and updated orders); ``_process_order`` is only
  used to attach a customer created offline.
* **Customers offline**: core 19 creates partners through a backend form, so
  only online. The quick-create here creates online, and offline stores the
  name and phone on the order (``earlydryer_new_partner_*``).
* **Price restriction**: core ``restrict_price_control`` + pos_hr roles; there
  is no per-employee discount limit in 19 Community, hence the rules and PINs.
* **Tag counters** are kept in ``localStorage`` (synchronous, written before
  printing) and cross-checked with the codes of the orders in IndexedDB,
  rather than in the core order store.
* ``_earlydryer_create_from_lines`` takes ``source_line_id`` (not
  ``pos_line_id``) and has no tag argument: tags are written on the items
  after creation; tagging's automatic server numbering is switched off for
  POS jobs (codes come from the till).
* Credit fallback when no credit rule matches: employees whose user is a
  Branch Manager.
* Tours need Chrome and ``websocket-client``, missing in the official
  ``odoo:19`` image: they skip there.

Open questions for Earlydryer
=============================

* Discount limits per role; who approves credit and from what amount (the
  rules shipped in demo are placeholders).
* Payment methods and card terminal providers per plant.
* Receipt wording and terms (placeholder text).
* Label printer model and label size per plant.
* Are quantity lines (5 shirts on one line) acceptable, or must each garment
  be entered separately?
* Photos for every order, or only damaged items?

Credits
=======

Authors
-------

* Secteur
