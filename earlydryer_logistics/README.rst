====================
Earlydryer Logistics
====================

Pickups from and deliveries to customers' homes and offices (Odoo 19.0
Community): delivery zones and fees told to the customer before delivery,
pickup / delivery slots, daily trips run by Earlydryer's riders or by a
third-party logistics company (3PL), a rider phone view with proof (signature,
photo, GPS) that keeps working offline, cash collected at the door reconciled
at the end of the day, and failed attempts with a reason.

Depends on ``earlydryer_reporting`` (and through it notifications,
accounting_ng, wallet, POS, tagging, laundry orders, catalogue and base), OCA
``base_location`` and ``fleet`` (vehicles and odometer logs). No Enterprise module, no paid maps
or routing API.

**Table of contents**

.. contents::
   :local:

Areas, zones and fees
=====================

**Areas** (``earlydryer.area``). OCA ``base_location`` 19.0 models cities
(``res.city``) and postal codes (``res.city.zip``, whose ``name`` is the code
and is required). Abuja areas are not postal codes: several areas share a
code and addresses are given by area and landmark. An area is therefore its
own small record, linked to its ``res.city`` (Abuja, FCT) and optionally to a
``res.city.zip``, with an optional centre point used for distance estimates.
25 Abuja areas are shipped (``noupdate``) as a **starting list with
approximate centres**, for Earlydryer to correct (*Configuration > Logistics
> Areas*).

**Zones** (``earlydryer.delivery.zone``): plant, areas, route order
(``sequence``), and the fee:

* ``flat``: ``flat_fee``;
* ``distance``: ``base_fee + fee_per_km × km``, not served beyond ``max_km``;
* ``express_fee`` on top for same-day / express;
* ``free_over_amount``: the delivery fee is waived from that order value
  (the express fee still applies); 0 = never free;
* ``min_order_amount``: below it, a Branch Manager must approve the delivery;
* ``pickup_fee``: pickups are free by default.

An area belongs to at most one zone per plant (constraint). An address in an
area without zone is *not served*: a Branch Manager sets a manual fee.

**Distance**: haversine distance between the plant (its address partner's
coordinates) and the address (its coordinates, else its area's centre) × the
road factor (*Settings > Earlydryer > Logistics*, default 1.3). It lives in
one method, ``earlydryer.logistics.quote._earlydryer_distance_km(origin,
destination)``, the place to plug a routing service later.

**Quote API** (backend wizards, POS, later earlydryer_api)::

    env["earlydryer.logistics.quote"].quote(
        partner, address_partner, branch, "delivery", date,
        express=False, order_amount=12500.0)
    # {"served", "zone_id", "zone_name", "area_id", "fee", "fee_breakdown",
    #  "distance_km", "below_minimum", "available_slots": [...], "message"}

Plain JSON-safe values. **Demo / placeholder values**: Central 1,500 flat;
Outer by distance 1,000 + 150/km up to 35 km, minimum order 3,000; South
2,000 flat, free over 20,000; express 1,000-1,500. Real values are open
questions.

**Fee products**: *Delivery Fee* and *Failed Delivery Fee* (service, kind
``delivery_fee``) in accounting_ng's *Delivery Fees* category: Delivery fee
revenue, service line Delivery. No tax on them here; accounting_ng's *Apply
VAT setting* handles VAT.

Addresses
=========

``res.partner`` (any contact used as a delivery address) gets the area, a
**landmark**, gate instructions, and the GPS accuracy and capture time.
Coordinates are core's ``partner_latitude`` / ``partner_longitude`` (in
``base`` in 19.0: ``base_geolocalize`` is not needed and its paid geocoders
are never called). They are captured by the rider at the first successful
stop, or replaced when the rider confirms a correction. Maps are links only
(Google Maps with the coordinates, else the address), opened in a new tab;
nothing is embedded.

Slots
=====

``earlydryer.logistics.slot.template`` per plant: weekday, local start / end,
pickups / deliveries / both, capacity, cut-off hours, optional zones.
``available_slots(branch, stop_type, date_from, date_to, zone=None)``
returns concrete slots with the places left, skipping past slots, slots
inside their cut-off, and public holidays (``resource.calendar.leaves``
without resource, on the plant's calendar or on no calendar). Times use the
plant calendar's time zone (default Africa/Lagos). The quote reuses it.

Stops
=====

``earlydryer.logistics.stop``: one pickup or delivery, numbered per plant
(``P1/STP/00031``). States: draft, scheduled, assigned (on a trip), en route,
arrived, done, failed, cancelled. The address is copied when the stop is
scheduled, so later edits of the contact keep history.

* **Book Pickup** (Front Desk, Customer Service, managers): customer and
  address, quote (fee and slots), tick a slot, notes. Sends
  ``pickup_booked``.
* **Arrange Delivery** on a job (button on the job, any packed / ready job):
  quote, slot, fee (managers may waive, with a reason), cash on delivery.
  Sends the new ``delivery_scheduled`` message, which carries the slot **and
  the fee**: the customer knows the fee before delivery.
* A job to deliver that becomes Ready without a delivery gets a draft stop
  (plant setting *Auto Draft Deliveries*) or a To Do for the plant's managers.

Charging the fee: ``_earlydryer_charge_fee(stop)`` (one method, for
earlydryer_corporate to override):

* job's sales order open and not fully invoiced: fee line(s) on the order;
* invoiced order, POS job, manual job: a small posted customer invoice
  linked to the job and the stop (``earlydryer_logistics_job_id``);
* waived or zero: nothing; pickups: when the bags are priced.

The job's ``_earlydryer_amounts()`` adds its posted fee invoices (total and
settled part); order lines are already in the order total, so a fee is
counted once (tested).

Pickups through to jobs (when the customer sees the price)
==========================================================

1. **At the door**: signature, photo of the bags, GPS, bag count, optional
   rough piece count, seal / bag tag numbers. **No pricing.** ``pickup_done``
   says the price follows once counted.
2. **At the plant**: *Logistics > Pickups Arrived* (done pickups without a
   job): *Price in POS* opens the plant's till (open session) with
   ``?earlydryer_pickup_stop=<id>``; a small POS patch starts an order for the
   customer, sets ``pos.order.earlydryer_pickup_stop_id`` (synced with the
   order) and adds the pickup fee line if any. *Price in Backend* creates a
   quotation (channel pickup) linked to the pickup; confirming it creates the
   job through the normal flow.
3. In both paths ``laundry.job._earlydryer_create_from_lines`` sees the
   pickup on the source order: channel ``pickup``, ``received_on`` = when the
   bags reached the plant (trip closed, or first pricing), delivery back when
   asked, and links the job to the stop. ``job_received`` then tells the
   customer the count and the price: **that is when they see the price**.
4. The return delivery uses the pickup's address.

Online booking (website and app)
================================

Customers book pickups themselves on the website
(``earlydryer_website_pickup``) or in the mobile app (``earlydryer_api``).
Both call one service, ``earlydryer.logistics.booking``. It is the only
public entry point: callers are anonymous, so it works as superuser and
checks every input itself.

* ``public_areas()``: the areas served by at least one plant (address
  picker).
* ``quote_pickup({"area_id", "date"?, "days"?})``: the plant (the zone
  with the lowest sequence that contains the area), the fee and the free
  slots.
* ``book_pickup(payload)``:

  * matches the customer by phone (E.164, ``0803…`` = ``+234803…``) or
    creates the customer;
  * reuses the same street in the same area, or adds a delivery address;
  * runs the quote again (**the fee always comes from the quote, never
    from the caller**);
  * locks the slot row so that two bookings cannot take its last place;
  * creates the stop (source *Website* or *Mobile App*) and **schedules it
    at once**: ``pickup_booked`` goes to the customer (if they agreed to
    messages), and the alert *Pickup booked online* goes to Branch Managers
    and Customer Service.

  If the area is not served or the slot is taken, nothing is booked: the
  caller gets the reason.
* ``request_callback(payload)``: the area is not served, or no time suits.
  The service creates a **draft** pickup and a To Do for the plant's
  Customer Service (fallback: its managers), with no fee and no message.
* ``get_pickup(ref, token)`` / ``cancel_pickup(ref, token)``: an online
  booking gets a random ``access_token``, so the customer can follow it and
  cancel it without logging in. Cancelling works while the pickup is still
  scheduled (not on a trip) and before the slot's cut-off.
* Limits:

  * ``client_ref`` (unique per source) makes a retried request return the
    same pickup;
  * at most 3 open online pickups per customer (system parameter
    ``earlydryer_logistics.online_max_open_pickups``).

After booking, an online pickup follows the normal flow: planning, trip,
rider, *Pickups Arrived*, pricing. *Logistics > Stops* has an *Online
requests* filter and a *Source* grouping.

Cash on delivery and door collections
=====================================

* Plant setting *Allow Cash on Delivery* (default on) and customer flag *No
  Cash on Delivery*.
* When a delivery is scheduled (and again when it joins a trip or loads)
  with an amount due and COD allowed, ``cod_amount`` = the job's amount due,
  fee included.
* Release rule: ``_earlydryer_check_release()`` also passes when the due
  amount is fully covered by the COD of an assigned (or en route / arrived)
  delivery stop; otherwise paid or approved credit, as before.
* At the door: **full collection** → done, job Delivered. **Short or
  nothing**: only with a manager's PIN in the rider view (an employee whose
  user may approve the credit rule; Branch Manager without rule), or a
  credit approved by phone and recorded by the office; otherwise the stop
  must be failed (*Unable to pay*) and the garments come back.
  ``alert_rider_cash_short`` fires whenever a completed delivery collected
  less than its COD.
* **Accounting**: on completion, a customer payment in the plant's **Rider
  Cash journal** (straight to the rider cash account) for the cash collected,
  reconciled with the job's open receivable: its invoices (an order still to
  invoice is invoiced first, invoice policy *on order*), its fee invoices or
  its POS customer-account receivable. Unmatched door payments (POS session
  still open) count as paid on the job and are matched when the session
  closes.
* **Transfer confirmed** (paid by transfer while the rider waited, confirmed
  by the office): no rider cash; listed in *Door Transfers to Match* for
  Finance to record in the bank journal and tick.

Rider cash handover and shortages
=================================

*Close Trip* (Branch Manager of the plant, Operations Manager, Finance):
every stop must be done or failed. Expected cash = cash collected; the
counted cash is handed over with accounting_ng's
``_earlydryer_rider_handover`` (Dr plant cash / Cr rider cash). A
**difference** is posted at once on the rider cash journal, naming the trip
and rider: shortage to the rider's receivable (their contact's receivable,
or the account set in settings) or to Cash over and short (setting
*Rider Cash Shortage*); overage to Cash over and short. Shortages also alert
the managers (``alert_rider_cash_short``). They are never written off
silently. The odometer reading goes to the vehicle's Fleet odometer log.

Failed attempts and the failed-delivery fee
===========================================

Failure reasons (*Configuration > Logistics > Failure Reasons*) have *fee
applies* and *note required*. A failed delivery goes back to Ready (job
state), sends ``delivery_failed`` to the customer and
``alert_failed_delivery`` to the managers (alert rule shipped). *Reschedule*
creates attempt + 1 (``previous_stop_id``), as a draft to quote again. The
delivery fee is not charged twice. **Failed-delivery fee (placeholder, off
by default)**: plant setting *None* / *Flat amount* / *Same as the delivery
fee*; when the reason says a fee applies, it is charged with the next
attempt through ``_earlydryer_charge_fee``.

3PL
===

A trip has a rider **or** a carrier (a contact flagged *3PL Carrier*) with
its reference and fee. Starting a 3PL trip hands every delivery over (jobs
Out for Delivery). There is no rider view: Operations records outcomes on
the stops (*Record Outcome*: same proof fields, carrier documents as
photos). *Create Carrier Bill*: draft vendor bill for the fee on the 3PL
expense account (setting; default the company expense account) with the
plant analytic; accounting_ng puts the vendor's WHT on the line.

Trips and planning
==================

``earlydryer.logistics.trip``: plant, date, label, rider (employee whose
user is a Rider, or a rider without login), vehicle, or carrier; draft →
planned → in progress → done. A stop belongs to one trip (many2one).

* **Daily Planning**: kanban of the day's stops grouped by trip, with the
  *None* column for unassigned stops; drag a stop to another trip, reorder
  inside a trip (sequence), COD totals in the column progress bars; filters
  by date, slot, zone.
* **Plan Automatically**: groups the day's scheduled stops by slot, then
  zone by zone (zone order) into trips of at most N stops (setting, a zone
  stays together unless it alone exceeds N), orders each trip by **nearest
  neighbour** from the plant on the stops' GPS (stops without GPS last, by
  zone order), and gives the trips to the selected riders round-robin. Draft
  trips to adjust. **Limits**: straight-line distances only, no road
  network, traffic, one-way streets or time windows; slots are respected
  only by grouping.
* **Starting** a trip: pickups are under way; each delivery waits for its
  **bag label scan** (job number Code128 of tagging's bag label, or any
  garment tag), which moves the job to Out for Delivery with the rider as the
  employee (release rule applies). Unscanned deliveries stay assigned and
  are flagged *not on board*.
* **Route sheet** PDF per trip: stops in order, customer, phone, address,
  landmark, gate, slot, jobs with their bag-label barcode, COD and a
  signature box for paper fallback.

Rider phone view
================

*Logistics > My Trips* (Rider group): today's planned and running trips,
*Start trip* (odometer when a vehicle is set), scan field, stop cards
(customer, area, landmark, slot, **COD in large type**, bags) with Call
(``tel:``), WhatsApp (``https://wa.me/...``) and Navigate (map link).
*Arrived* records GPS and time; *Done* takes the signature (small canvas),
recipient, photos (camera input, resized to 1280 px JPEG 0.7 in the browser,
like the POS photos), cash and method, manager PIN when short, bag count for
pickups; *Failed* takes a reason and a note.

**Phone setup**: log in to Odoo on the Android phone (Chrome) with the
rider's user; allow **location** for the site when asked (Chrome site
settings: Location = Allow); *Add to Home screen* from the Chrome menu;
keep the screen open on *My Trips* during the round. ``web_responsive``
makes the shell usable at phone width.

**GPS**: accuracy is recorded; worse than the threshold (default 100 m) is
flagged *low GPS accuracy*, never refused. Without coordinates on the
address, *Save this location for the customer* stores them once the stop
has synced; with coordinates, the rider may confirm they are wrong.

Offline behaviour
=================

Every action is stored in IndexedDB first (per user), applied to the
screen at once, and sent in order when the network is back (on the
browser's *online* event and every 20 s), with a visible *pending sync*
counter. Photos wait in IndexedDB and upload after their stop's actions
synced. Each server method is **idempotent per client UUID**
(``earlydryer.logistics.client.action``): a retry returns the stored result.
Actions the server refuses (e.g. a release refused at the bag scan) are
shown and dropped.

Limits: the Odoo web client cannot be **loaded or reloaded offline**: open
*My Trips* while online and keep it open; the trip data stays in the open
screen (and is cached for the next load). Offline, a manager PIN cannot be
checked: the stop is completed on the phone and, if the server refuses the
PIN when it syncs, the stop is flagged *Needs review* with a To Do for the
managers (what happened at the door is never reversed). Bag scans offline
are queued; the stop shows *not scanned* until the server accepted the scan.

Reporting and alerts
====================

Logistics KPIs are registered with ``earlydryer_reporting``'s KPI service,
following its README: one private method on ``earlydryer.kpi`` and one
``REGISTRY`` entry each (``models/earlydryer_kpi.py``): pickups done,
deliveries done, done within the slot (%), failed stops (%) with the top
five reasons (``top_reasons``), stops per closed trip, delivery fee revenue,
cash collected at the door, rider cash differences and 3PL cost. Each has a
per-plant breakdown, the previous-period comparison and a drill-down to the
stops, trips or fee invoice lines. The owner dashboard gets a **Logistics**
section (JS patch); the server returns these KPIs to Operations Managers,
Management and Administrators only, so the section stays hidden for others.
Stop and trip pivots group by rider, zone, reason and date.

Note: ``REGISTRY`` is a module-level dictionary of earlydryer_reporting, so
on a server hosting several databases, one with earlydryer_reporting but
without this module would list the logistics codes too (the dashboard asks
for every registered code). Install both together, or run one database per
server, as in production.

Notifications (drafts, to submit to Meta like the others): customer
``delivery_scheduled`` (slot, fee, COD) and ``delivery_failed``; staff
``alert_rider_cash_short``. Alert rules shipped (placeholder thresholds 0):
failed delivery or pickup → Branch Managers; rider cash short → Branch
Managers and Finance.

Security
========

=====================  ============  ==========  ==========  =============  ============  ======  ==========
Group                  Book/arrange  Plan trips  Rider view  Close / cash   Zones, slots  Waive   Door credit
=====================  ============  ==========  ==========  =============  ============  ======  ==========
Front Desk             yes           no          no          no             read          no      no
Customer Service       yes           no          no          no             read          no      no
Rider                  no            no          own trips   no             read          no      no
Branch Manager         yes           own plant   no          own plant      read          yes     per rule
Operations Manager     yes           all         no          all            yes           yes     per rule
Finance                read          read        no          yes            read          no      no
Administrator          full          full        full        full           full          full    full
=====================  ============  ==========  ==========  =============  ============  ======  ==========

Branch record rules on stops and trips are given to the office roles (Front
Desk, Customer Service, Branch Manager, Finance; all plants with
``group_all_branches``); Riders get only ``rider_user_id = user`` (their
trips and those trips' stops). Riders have read-only access rights: the
phone API checks the trip is theirs and works with sudo. Everything is
checked in Python (``_earlydryer_check_right``), not only in the views:
protected stop and trip fields (state, cash, charges) are written only by
the engine. Note: Branch Managers imply the Rider group in earlydryer_base,
so they can also open *My Trips* for trips assigned to them.

OCA ``auditlog`` rules (confirmed by the ``post_init_hook``) on zones,
stops (signature excluded) and trips; auditlog 19 logs whole models.

Odoo 19 notes and deviations
============================

* Areas: own model (see above), not ``res.city.zip``.
* Coordinates: core ``partner_latitude`` / ``partner_longitude``, no
  ``base_geolocalize``.
* Signature: the backend forms use core's ``signature`` widget; the rider
  view uses a small canvas, because core's signature dialog loads its
  library lazily, which fails offline.
* Photos are uploaded through a JSON-RPC model method (base64, like the POS
  photos and the rest of the queue), not a multipart HTTP route.
* POS link: ``pos.order.earlydryer_pickup_stop_id`` is a many2one the 19 POS
  keeps as a raw id (its comodel is not loaded in the POS); it travels with
  the order and the job links back at sync.
* Planning board: kanban grouped by trip (drag and drop works in 19), not a
  custom OWL screen.
* Riders pick from ``hr.employee.public`` in the planning wizard (Branch
  Managers have no HR rights).
* HTTP tours need Chrome and ``websocket-client``, missing from the official
  ``odoo:19`` image: no tour; the rider API is covered by Python tests.

Open questions for Earlydryer
=============================

* **Coverage and pricing**: areas served by each plant; flat zones or
  distance pricing; free-delivery threshold; express fee; minimum order;
  pickup fee.
* **Scheduling**: slot times and capacity per plant and weekday; cut-off.
* **Pickups**: who counts and prices pickups (plant intake is the default);
  is a rough count at the door useful?
* **Online booking**: should online pickups be scheduled at once (shipped)
  or reviewed first; the cap of open pickups per customer (3); should the
  website pickup page ask customers to log in.
* **Cash and failures**: is COD allowed, and for whom; the failed-delivery
  fee rule (placeholder: none); how rider cash shortages are treated (rider
  receivable or cash over and short) and recovered.
* **Riders and 3PL**: number of riders and vehicles; which 3PL partners, how
  they are paid (per trip, per stop, monthly) and whether they collect cash.
* The Abuja area list and centre points.

Credits
=======

Authors
-------

* Secteur
