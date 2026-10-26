==================
Earlydryer Tagging
==================

Every garment piece gets a **tag with a barcode** at intake. Staff find any
garment's order by scanning it, move orders through the stages by scanning,
and catch mix-ups at packing (a garment in the wrong bag, or one missing).

Depends on ``earlydryer_laundry_order`` (jobs, items, stage moves),
``barcodes`` (scanner service, error sound) and ``web``.

**Table of contents**

.. contents::
   :local:

Two kinds of tags
=================

Each plant chooses its *Tag Mode* (plant form, *Tagging* tab).

**Printed tags** (default)
  Odoo numbers the tags and prints them on thermal or heat-seal labels.
  With *Assign Tags at Intake* (default on) every item that needs a tag gets
  its code when the job is created, so the walk-in flow is: confirm the order,
  *Assign & Print Tags*, attach. The button also moves the job to *Tagged*.
  A printed code is unique for ever in the company, even after the order is
  closed, and a replaced code stays reserved.

**Pre-printed reusable tags**
  Numbered tags bought in rolls. *Scan Tags* opens a list of the garments: click
  the first *Tag* cell and scan each physical tag in turn (the scanner's Enter
  moves to the next row). The code must match the plant's *Pre-printed Tag
  Pattern* (default ``^[A-Z0-9]{4,16}$``). A code is unique among the **open**
  jobs of the plant; once the order is delivered, collected, uncollected or
  cancelled, the tag can go on another garment. Scanning a reused code finds
  the open job first.

Only items whose service has *Requires Tag* need one. A job can only move to
*Tagged* when every such item has a valid code (``_check_can_tag``).

Code format and check digit
===========================

Printed code: ``<prefix><7-digit number><check digit>``, for example
``P100001230`` (prefix ``P1``, number 123, check digit 0). No dash or space,
so the Code128 barcode stays short and reads reliably.

* **Prefix**: per plant (default the plant code), upper-case letters and
  digits, unique across plants. It tells which plant the garment belongs to.
* **Number**: the plant's tag sequence (``ir.sequence``, *no gap*, padding 7,
  created automatically for every plant). 9,999,999 tags per prefix.
* **Check digit**: mod-10 (Luhn) over the 7 digits. Any single wrong digit and
  any swap of two neighbouring digits (except 0/9) is rejected **before any
  database lookup**. The plant setting *Check Digit* can switch it off (codes
  then have 7 digits after the prefix); change it only before the first tag.

``earlydryer.tag.code`` (abstract model) holds the logic:
``generate(branch)``, ``is_valid(code, branch=None)``, ``branch_for(code)``,
``parse(code)``, ``format_number(branch, number)``. The prefixes are read from
a cached map, so validating a code costs no query.

Uniqueness replaces the SQL unique index of ``earlydryer_laundry_order``
(``(earlydryer_branch_id, tag_code)``), which would forbid reusing a
pre-printed tag. Odoo 19 keeps model table objects in a dictionary keyed by
name, so redeclaring ``_tag_branch_uniq`` as a plain ``models.Index`` with the
same name replaces the definition: on install/update Odoo sees the definition
changed, drops the unique index and creates a plain one (still used by the
lookups). Uniqueness is then checked in Python (``_check_tag_code_unique``),
with a message naming the job holding the tag. If this module is
uninstalled, updating ``earlydryer_laundry_order`` recreates the unique index
(it fails if pre-printed codes are reused at that time).

Tag ranges for the offline POS
==============================

A till printing tags while the internet is down needs numbers nobody else
uses. ``earlydryer.tag.range`` is a block of numbers of the plant's tag
sequence, held by a till (``pos.config``):

* ``_earlydryer_allocate_range(branch, pos_config, size=500)`` takes the
  block in one go (the sequence row is locked), so server codes and range
  codes never collide. Ranges of a plant never overlap (constraint).
  *Allocate Tag Ranges* on the plant form gives one to every till without one
  (Branch Manager).
* ``_earlydryer_consume(code)`` is called whenever a printed code is written
  on an item that was not generated on the server (POS sync, typed code): it
  advances ``next_number`` (the highest used number + 1, out-of-order syncs
  are fine) and marks the range *Exhausted* after its last number. A code
  outside every range is refused unless the plant's sequence already issued
  it; a code of a cancelled range is refused.
* Top-up: daily cron, and on every POS session opening, a till with less than
  20% of its numbers left (or no range) gets the next block of the same size.
* ``_earlydryer_pos_data()`` gives the plain values ``earlydryer_pos`` will load
  into the POS session (prefix, check digit flag, numbers).

Labels
======

Two QWeb PDF reports, sized by paperformats (editable, *Settings > Technical >
Reporting > Paper Format*), chosen per plant on the *Tagging* tab:

* **Garment tag** (one label per item): Code128 of the tag code and the code
  in clear, job number, customer short name (first name and initial, never
  the phone), garment category, service code, piece ``n/N``, EXPRESS badge,
  promised date. Labels at most 20 mm high use a one-line *strip* layout
  (barcode left, details right) for heat-seal strips.
* **Bag / order label** (one per job): job number as Code128 and QR code,
  customer, item count, shelf, promised date, EXPRESS badge.

Shipped sizes: thermal 50 × 25 mm (garment), heat-seal strip 60 × 15 mm
(placeholder), thermal 100 × 50 mm (bag) and an A4 sheet for testing on an
office printer (3 × 8 garment labels, 2 × 5 bag labels). Margins are zero
and DPI 96 so HTML millimetres equal paper millimetres; the barcode PNG is
generated at 800 px and shown at the label width, so it is never scaled up.

Buttons on the job: *Assign & Print Tags* (front desk; printed mode),
*Scan Tags* (pre-printed mode), *Reprint Tags*, *Print Bag Label*. On the job
list: *Actions > Print Tags* for the selected jobs. Every reprint is logged in
the chatter with who and how many. *Actions > Download Tags (ZPL)* produces a
``.zpl`` text file from the plant's *ZPL Template* (placeholders ``{code}``
``{job}`` ``{garment}`` ``{service}`` ``{piece}`` ``{customer}``
``{promised}`` ``{express}`` ``{branch}``), only for Zebra-compatible printers
set up to receive files; PDF is the default path.

Printer setup notes
-------------------

The Odoo server is in a data centre, never on the plant LAN: labels are
printed **from the browser** on the counter PC.

1. Install the label printer's own driver on the counter PC (Windows: the
   maker's driver, not "Generic / Text Only").
2. In the driver, set the label size to the paperformat (e.g. 50 × 25 mm),
   the media type (gap / black mark / continuous) and the darkness.
3. Print the PDF from the browser's PDF viewer with **margins off / none**,
   **scale 100% / actual size** (not "fit to page"), and the label printer
   selected. Chrome remembers the last settings per printer.
4. Check the first label with a scanner or a phone barcode app.

Scanning
========

Scanners are USB or Bluetooth keyboard-wedge devices: they type the code and
press Enter. *Earlydryer > Operations > Scan* is a small OWL client action
(no Enterprise Barcode app):

* **Find**: scan a tag or a job number; a card shows job, stage, customer,
  shelf and amount due, with *Open Job*.
* **Move**: choose the stage and who did the work, then scan garments; each
  scan is checked at once and listed, *Done* moves the jobs. With the plant
  setting *Move on Each Scan* every scan moves its job immediately.
* **Pack**: scan the bag label (or job number, or any of its garments), then
  each garment. The screen shows *scanned / expected* and the garments still
  missing. A garment of another job or plant raises a **blocking red alert**
  with the other job's number and the error sound. Scanning another job's
  bag label only offers to switch. *Finish Packing* moves the job to Packed
  when every garment was scanned. A Branch Manager can instead *Mark the
  Rest Missing* with a note: ``earlydryer_laundry_order`` does not pack a job
  with missing items, so the job then waits for the garment or the claim.

The input keeps the focus after each scan; scans arriving while the focus is
elsewhere are caught by the ``barcode`` service of the ``barcodes`` module.

Packing gate: when the plant has *Scan Every Item at Packing* (default), a
job only moves to Packed once every tagged, non-missing item has
``packed_scanned``. Any backward move (QC rework...) clears the packing scans.

Scan API
--------

Model methods on ``laundry.job``, JSON-safe, for this screen, the production
board (``earlydryer_production``) and the POS::

    env["laundry.job"].earlydryer_scan_lookup("P100001230")
    # {"type": "item", "job_id": 42, "item_id": 311, "job_name": "P1/26/00042",
    #  "state": "washed", "customer": "Adaeze Okonkwo", "branch_id": 1,
    #  "shelf": "", "amount_due": 0.0, "message": "...", ...}
    # type: item | job | unknown | invalid. A wrong check digit is "invalid"
    # without any search; a code of a plant the user cannot see is "unknown".

    env["laundry.job"].earlydryer_scan_move(
        ["P100001230", "P100001248", "P1/26/00043"], "sorted", employee_id=7)
    # [{"code", "result": ok|duplicate|refused|invalid|unknown, "job_id",
    #   "job_name", "item_id", "message", "warning"}, ...]
    # one action_move_to per job with the scanned items (stage log), warning
    # when a job still has garments not scanned.

    env["laundry.job"].earlydryer_pack_start("P1/26/00042")
    env["laundry.job"].earlydryer_scan_pack(42, "P100001230", employee_id=7)
    # {"result": ok|duplicate|wrong_job|wrong_branch|unknown|invalid,
    #  "other_job_name", "bag", "scanned", "expected", "missing_items", ...}
    env["laundry.job"].earlydryer_pack_finish(42, 7)
    env["laundry.job"].earlydryer_pack_finish(42, 7, note="...", mark_missing=True)

Scan log and mismatch alerts
============================

``earlydryer.scan.log``: one row per scan through the API (date, code, mode,
result, job, item, expected job, user, employee, plant). Append-only: only an
Earlydryer Administrator may change or delete rows. Each ``wrong_job`` or
``wrong_branch`` at packing posts a note on both jobs and schedules a To Do
for the plant's manager through ``_earlydryer_on_scan_mismatch(log)``, which
``earlydryer_notifications`` will extend with a WhatsApp alert.

*Operations > Scan Log* (own scans; Branch Managers: their plants) and
*Packing Mismatches* (pivot by day, plant and user).

Security
========

========================  ============  ====  ====  ====  ================  ============  ========
Group                     Assign/print  Find  Move  Pack  Replace tag       Ranges        Scan log
========================  ============  ====  ====  ====  ================  ============  ========
Front Desk                yes           yes   yes   yes   pre-printed only  read          own
Production, QC            reprint only  yes   yes   yes   no                no            own
Rider                     no            yes   no    no    no                no            no
Branch Manager and above  yes           yes   yes   yes   yes               create/write  plants
Earlydryer Administrator  yes           yes   yes   yes   yes               full          full
========================  ============  ====  ====  ====  ================  ============  ========

The checks are in the Python methods (``_earlydryer_tag_rights``), not only in
the views. Typing over an existing tag is refused below Branch Manager: use
*Replace Tag* (reason required, old code kept in *Replaced Tags* and the
chatter). Tag code changes are audited by the ``laundry.job.item`` auditlog
rule of ``earlydryer_laundry_order`` (OCA auditlog 19 logs whole models, with
fields to exclude only, and allows one rule per model).

Demo data
=========

Plant 1 uses printed tags, Plant 2 pre-printed tags (``ED200001``...) on the
heat-seal size, so both paths can be tried. The demo jobs get tags, the Plant
1 counter holds a range, and the scan log has a few rows including a packing
mismatch (with its To Do for the Plant 1 manager).

Open questions for Earlydryer
=============================

* Printed or pre-printed tags, or both (per plant)?
* Label printer make and model, label size and media (gap / black mark);
  thermal transfer or direct thermal?
* Heat-seal tags for delicate items: which machine and strip size?
* Scanner model (USB or Bluetooth, Code128 and QR enabled, Enter suffix)?
* Should Move commit per scan or per batch (*Move on Each Scan*)?
* Who may replace a lost tag (now: Branch Manager; front desk too for
  pre-printed tags)?
* Missing garments at packing: may the job be packed without them (today
  ``earlydryer_laundry_order`` refuses), or wait for the claim?
