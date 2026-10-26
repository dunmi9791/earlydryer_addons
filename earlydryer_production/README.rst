=====================
Earlydryer Production
=====================

The screens and records a plant uses to move orders through processing: a
**stage board** for the front desk (and a shared **production tablet**),
**sorting** into colour groups, optional **wash and dry batches**, a **QC
screen** with rework reasons, and the **machine status** from the Maintenance
app. Every stage move records which staff member did the work and where it was
recorded, for productivity per stage per person.

Depends on ``earlydryer_tagging`` (scan API, packing gate), ``maintenance``
(equipment and requests), ``hr`` (badges and PINs), ``bus`` (live board) and
``web`` (OWL client action). Machine-load scheduling and consumable posting are
deliberately out of scope.

**Table of contents**

.. contents::
   :local:

Production modes and the tablet
===============================

Each plant chooses its *Production Mode* (plant form, *Production* tab):

**Front Desk** (default)
  The front desk moves orders on the board (drag a card, or tick cards and
  *Move to…*). Moving to a production stage (Sorted, Washed, Dried, Ironed,
  QC, Packed) first shows big buttons with the photo and name of the plant's
  staff, most recent movers first: one drag plus one tap.

**Production Tablet**
  A shared tablet in the production area. A person scans their badge (or taps
  *PIN* and types it); the board shows who is identified. They choose the
  stage at the top (Sorted … QC) and scan garments or job numbers: each scan
  moves the job with ``earlydryer_scan_move`` under their name. After
  *Tablet Idle Time* (default 120 s) without activity the tablet forgets them
  and asks again, so nobody's work is recorded under someone else's name.

**Both**
  The board shows a *Tablet mode* toggle.

Setting up a tablet
-------------------

1. Create one Odoo user per tablet, e.g. *Production Tablet P1*, with the
   **Production Staff** role (or **Quality Control** if QC staff use it),
   allowed and default branch = the plant. The user logs in once and stays
   logged in; the identified *employee* is recorded as who did the work
   (``laundry.job.stage.log.employee_id``), the tablet user as who recorded
   it (``user_id``).
2. Give each employee of the plant a **Badge ID** and/or a **PIN** (employee
   form, *HR Settings* tab, HR officers) and set their *Earlydryer Plant*.
   *Print Plant Badge* (employee form header) prints an ID-card-sized badge
   (85.6 × 54 mm) with photo, name, plant and barcode; it generates a badge ID
   when there is none.
3. Open *Earlydryer → Operations → Stage Board* on the tablet.

Badges and PINs only match employees of that plant or employees without a
plant. Five wrong codes within two minutes lock that browser session for two
minutes. Every attempt is logged in *Production Reports → Tablet Sign-ins*
(codes are never stored). The server enforces the idle time too: each move
carries a token that is refused once the tablet was idle too long.

The stage board
===============

Columns Received → Ready (plus *Out for Delivery* when the plant has delivery
jobs); final stages are counters (closed today). Cards show the job number,
customer short name, item count, OVERDUE / EXPRESS / Rework / Balance due
badges, the promised time (``in 3 h``, ``2 h late``), the shelf when packed or
ready, garments still to sort, and the batch progress (``3/5 washed``).
Within a column: overdue first, then express, then promised time. Column
headers show the count and the age of the oldest card in that stage.

The scan bar keeps the focus. Front desk mode: scanning a tag or job number
highlights the card and offers its next stage (Enter accepts). Errors from the
server (missing tags, QC not passed, no shelf, unpaid release, rights…) appear
on the card; the board never changes a stage on its own. Clicking a card opens
a side panel: garments, recent moves with their source, *Open Job*, *Sort*,
*QC*, *Print Bag Label*, *Next*.

Server methods
--------------

All on ``laundry.job``; the board only calls these (plain JSON):

``earlydryer_board_data(branch_id, filters)``
  Public wrapper of ``_earlydryer_board_data``: branch (users without
  *See all branches* are kept on their own plants), columns with sorted cards,
  final counters, employees, machine strip, rights. ``filters``:
  ``express``, ``overdue``, ``due_today``, ``channel``, ``search`` (job
  number, customer or tag).
``earlydryer_board_cards(job_ids, branch_id)``
  Fresh cards (``_earlydryer_board_card``) and the ids that left the board.
``earlydryer_board_move(job_ids, target_state, employee_id, note, tablet_token)``
  One ``action_move_to`` per job in a savepoint; returns per-job results and
  the new cards.
``earlydryer_board_job_detail``, ``earlydryer_board_open_sort``, ``earlydryer_board_open_qc``
  Side panel and dialogs.
``earlydryer_tablet_identify(code, branch_id)``, ``earlydryer_tablet_scan(code, branch_id, target_state, token)``, ``earlydryer_tablet_release(token)``
  The tablet. ``hr.employee._earlydryer_identify(code_or_pin, branch_id)``
  does the matching and rate limiting.

Methods starting with ``_`` cannot be called from the web client in Odoo, hence
the public wrappers.

Live updates (bus)
------------------

After every successful stage move (``_earlydryer_on_state_changed``) and QC
pass, the branch sends ``earlydryer.board/updated`` with
``{"branch_id", "job_ids"}`` on the channel ``(earlydryer.branch, "earlydryer_board")``
(``bus.listener.mixin``). A breakdown sends ``earlydryer.board/machines``.
Notifications leave at commit, so a refused move never notifies.

Boards ask for the string channel ``earlydryer_board_<branch id>``;
``ir.websocket._build_bus_channel_list`` replaces it by the branch channel only
when the user works on that branch. When the websocket is not connected the
board reloads every *Board Refresh* seconds (default 30).

The standard job kanban of ``earlydryer_laundry_order`` stays as a fallback.

Stage log: source and item count
================================

``laundry.job.stage.log`` gets ``source`` (board, tablet, scan, batch, qc,
form, system) and a stored ``item_count`` (garments the move covered, or the
job's count). Entry points set the context key ``earlydryer_move_source``
before calling ``action_move_to``; the log reads it when it is created
(``system`` for superuser moves such as the uncollected cron, ``form``
otherwise).

*Production Reports → Stage Productivity* (Branch Manager and above): pivot
employee × day × stage, measures garments and moves. *Moves without
Employee* lists production-stage moves without who did the work (should stay
empty).

Sorting
=======

``laundry.job.item.colour_group``: Whites, Lights, Darks, Colours, Delicates,
Special. Proposed from ``earlydryer.service.type.default_colour_group``
(installed: Dry Cleaning, Shoe, Bag and Rug Cleaning → Special; others empty).
The *Sort* dialog (job form button, board side panel, or automatically when a
card with unsorted garments is moved to Sorted) lists the garments with one
button per group. With *Colour Group Required at Sorting* (default on) a job
cannot enter Sorted while a garment (not missing) has no group.

Wash and dry batches
====================

Only for plants with *Wash and Dry Batches* on (*Operations → Wash & Dry
Batches*). A batch (``P1/WB/00012``) has a type (wash/dry), a machine of the
plant of a matching type, garments waiting in Sorted (wash) or Washed (dry),
who ran it, program, optional load weight and notes.

* A garment is in at most one open (draft or running) batch of a type.
* *Start* refuses a machine that is down or already running a batch; a
  Branch Manager may start anyway with an *Override Reason* (posted). With
  *Load Weight Required* the weight must be entered first.
* *Suggest Garments* proposes waiting garments, express first then oldest,
  up to the machine's capacity when every garment category has an average
  weight, otherwise up to *Suggest up to* garments. A proposal only.
* *Done*: with *Finished Batch Moves Jobs* (default on), each job of the
  batch whose garments needing that stage have **all** been through a finished
  batch of that type (since the job last entered Sorted/Washed, so a QC rework
  starts over) moves to Washed / Dried through ``action_move_to``, with the
  batch's employee and garments, source ``batch``. Garments whose service skips
  the stage do not count. Jobs not fully covered stay and show ``2/5 washed``.
  A job that cannot move (a gate) is noted on the batch.

No stock moves or consumables are posted.

QC and rework reasons
=====================

*Operations → QC* lists jobs at QC, express on top, oldest first. *Check*
opens the dialog: per garment Pass or Fail with a reason, the stage to send it
back to (from the reason), an optional photo and note. *All Passed → Pack*
passes and packs through the normal API; when the plant scans garments at
packing it opens the tagging Pack screen instead.

``earlydryer.rework.reason`` (*Configuration → QC Rework Reasons*): stain
remains, not clean, poor ironing, wrong fold, colour run, damage found
(damage), missing button or accessory (damage) — placeholders.

``action_qc_fail(items, employee, return_to_state=None, note=None, reason=None, photo=None, details=None)``
extends ``earlydryer_laundry_order``: it stores one ``laundry.job.item.rework``
per garment (reason, from/to stage, employee, note, photo; the photo is also
added to the garment's photos). With several reasons the job returns to the
earliest stage asked. *QC Reason Required* (default on) refuses a fail without
a reason. ``rework_count`` is still kept by ``earlydryer_laundry_order``.

When a reason is a damage: a note on the job (with the photo), a To Do for the
branch manager, then the hook ``laundry.job._earlydryer_on_damage_found(rework)``
— empty here, ``earlydryer_claims`` opens the claim from it.

Machines and Maintenance
========================

``maintenance.equipment`` gets an optional *Plant* (equipment without one is
not production equipment and keeps the core rules), a *Machine Type* (washer,
dryer, iron/press, steam boiler, dry-cleaning machine, other) and a capacity
in kg. Status (computed):

* **Down** — an open corrective request: ``maintenance_type = 'corrective'``,
  stage not done (``stage_id.done``; Odoo 19 has no ``maintenance.stage.done``
  model), not archived. Preventive requests do not stop a machine.
* **In Use** — a batch is running on it.
* **Available** otherwise.

The board and the batch form show the status. *Report Breakdown* (board,
machine list or form) asks the machine, what happened, an optional photo and
who reports it, and creates a high-priority corrective request for the
machine's maintenance team. Registers, preventive schedules and repairs stay in
the standard Maintenance app.

Rights added: core lets internal users read only the equipment they follow;
Front Desk and Production read the machines of their plants, Branch Managers
configure them (*Production Setup → Plant Machines*), and see the requests of
their plants' machines. Requests are created by the wizard with superuser
rights after checking the user may report: ``hr_maintenance`` (auto-installed
with ``hr`` + ``maintenance``) computes the request owner from the equipment's
employee, so the core "own requests" rule would refuse the reporter; the
reporter is added as follower.

Security
========

========================  =========  ======================  ====  ===========  ====  =========  ========  ============
Group                     Board      Move                    Sort  Batches      QC    Breakdown  Machines  Productivity
========================  =========  ======================  ====  ===========  ====  =========  ========  ============
Front Desk                yes        yes                     yes   read         no    yes        read      no
Production Staff          yes        up to QC (not Packed+)  yes   create, run  no    yes        read      no
Quality Control           yes        yes                     yes   create, run  yes   yes        read      no
Rider                     read only  no                      no    no           no    no         no        no
Branch Manager and above  yes        yes, overrides          yes   full         yes   yes        config    yes
Earlydryer Administrator  full       full                    full  full         full  full       full      full
========================  =========  ======================  ====  ===========  ====  =========  ========  ============

Enforced in Python: ``action_move_to`` (move rights, Production Staff stop
before Packed), ``action_qc_pass`` / ``action_qc_fail`` (QC group), batches
(``group_production``), the breakdown wizard. Record rules follow the base
branch pattern for batches, reworks, tablet sign-ins and plant machines.

Demo data
=========

Plant 1: front desk mode, no batches. Plant 2: both modes, batches on.
Badges ``BADGE-P1-01``…, PINs ``1101``…/``2201``…; tablet logins
``ed_tablet_p1`` / ``ed_tablet_p2`` (password = login). Washers, dryers and a
press per plant; *P1 Washer B* has an open breakdown. A running wash batch, a
finished dry batch and a draft on plant 2; QC reworks including a damage (with
the manager's To Do) on plant 1.

Known limits
============

* The earlier modules' tests move jobs without sorting and fail QC without a
  reason: ``earlydryer_laundry_order``'s test setup turns *Colour Group
  Required at Sorting* and *QC Reason Required* off when this module is
  installed (this module's own tests turn them back on).
* The browser tour (``tests/test_board_tour.py``) is skipped on the official
  ``odoo:19`` image, which has neither Chrome nor ``websocket-client``.
* Final-stage counters count jobs closed today.

Open questions for Earlydryer
=============================

* Who records the employee for each stage: the front desk, or production staff
  on a tablet? (Both are supported per plant.)
* Do you want batch records at all?
* Will you weigh wash loads (cost per kg)?
* What are your real colour groups and QC failure reasons?
* How many washers, dryers and presses per plant, of what capacity?
* Should damage found at QC stop the order until the claim is decided?
