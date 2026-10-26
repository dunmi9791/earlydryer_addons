============================
Earlydryer Service Catalogue
============================

What Earlydryer sells, how each item is priced, the surcharges on top and the
turnaround promise (Odoo 19.0 Community). Depends on ``earlydryer_base``; used
by ``earlydryer_laundry_order``, ``earlydryer_pos``, ``earlydryer_api`` and
``earlydryer_corporate``.

**Table of contents**

.. contents::
   :local:

Data model
==========

+----------------------------------+------------------------------------------------------------+
| Model                            | Purpose                                                    |
+==================================+============================================================+
| ``earlydryer.garment.category``  | Shirt, agbada, duvet... ``code`` (unique, upper-case),     |
|                                  | ``garment_group``, ``piece_count`` (a 3-piece suit gets 3  |
|                                  | tags), ``average_weight_kg``, ``image_128`` (POS buttons). |
+----------------------------------+------------------------------------------------------------+
| ``earlydryer.service.type``      | Wash & iron, dry cleaning... standard and express          |
|                                  | turnaround (working hours), express surcharge (percent or  |
|                                  | fixed), ``requires_tag``, ``allowed_category_ids`` (empty  |
|                                  | = any), ``pos_category_id``.                               |
+----------------------------------+------------------------------------------------------------+
| ``product.template`` (extended)  | ``earlydryer_kind``: ``laundry`` / ``surcharge`` /         |
|                                  | ``express`` / ``retail``. A laundry product is one garment |
|                                  | category × service type (``Shirt - Wash & Iron``,          |
|                                  | ``SHIRT-WI``), a service product, so sales, POS, invoicing |
|                                  | and price lists work unchanged. Turnaround fields computed |
|                                  | from the service type, with per-product overrides.         |
+----------------------------------+------------------------------------------------------------+
| ``earlydryer.surcharge``         | Silk, lace, beads, oversized... ``kind``,                  |
|                                  | ``compute_mode`` (``fixed`` / ``percent``), its own        |
|                                  | ``product_id`` (auto-created), where it applies.           |
+----------------------------------+------------------------------------------------------------+
| ``product.pricelist`` (extended) | ``earlydryer_branch_id`` (empty = all plants),             |
|                                  | ``earlydryer_channel`` (``walk_in`` / ``pickup`` /         |
|                                  | ``corporate``), ``earlydryer_is_contract``.                |
+----------------------------------+------------------------------------------------------------+
| ``earlydryer.catalog``           | Abstract service: pricing, turnaround and catalogue API.   |
+----------------------------------+------------------------------------------------------------+

Constraints: one active laundry product per (category, service type,
company); one active non-contract price list per (plant, channel, company);
contract lists use the Corporate channel; a plant list needs a channel.
Both uniqueness rules are partial unique indexes (``models.UniqueIndex``), so
archived records do not count.

Pricing rules
=============

* Per item only, never per kg. The price computed at intake is final.
* **Surcharges and express are always separate order lines**, linked to their
  garment line by the order modules, never a hidden change of the garment
  price. Invoices stay readable, the offline POS can do the same, and reports
  separate base revenue from surcharges.
* Fixed surcharges price their own product through the same price list as the
  garment (add price list items on the surcharge product to vary it by plant or
  channel; without an item, the product's sales price is used). Percent
  surcharges are a percentage of the garment unit price.
* Express comes from the service type: percent of the garment unit price, or a
  fixed amount (company currency). It is invoiced on the ``EXPRESS`` product
  (``earlydryer_service_catalog.product_express``).
* Currency rounding is applied at the end, on each unit price; ``total`` is
  the sum of the rounded unit prices × quantity.

Price list resolution (``product.pricelist._earlydryer_resolve_pricelist``):

#. the commercial partner's price list, if it is an active contract list (and
   valid for the plant when the contract has a plant);
#. the price list of (plant, channel);
#. the price list of (no plant, channel);
#. the company default price list (never an Earlydryer one), with a warning in
   the log.

Annual price update
-------------------

On an Earlydryer price list, *New Price Version* (Management): pick an
effective date (in the future), an optional percentage and a rounding (e.g. 50
for the nearest ₦50). The items valid on that date are copied with
``date_start`` = effective date 00:00 (user's time zone, default
Africa/Lagos); the old items get ``date_end`` = one second before, i.e. the
end of the previous day. The percentage only changes *fixed* prices; items
computed from another list or a formula are copied as they are. Past prices
are never edited, so older orders recompute the same prices.

Point of sale
-------------

*Sync POS Price Lists* on the branch form (Management) sets, on every POS of
the plant: *use price lists*, the plant's walk-in list (or the channel-only
one) as default, and walk-in + every contract list valid in the plant as
available. The POS session then loads these lists and their currently valid
items, and contract clients get their list from their partner record, so all
of it works offline. It is a button on purpose: it is not triggered by price
list changes.

The POS category of each service type is created by the generator (under
*Laundry*); surcharges and express are in *Surcharges & Express*, retail in
*Retail*.

Usage for later modules
=======================

::

    catalog = self.env["earlydryer.catalog"]
    product = catalog.get_laundry_product(category, service_type)  # UserError if not sold
    result = catalog.price_item(
        product, partner, branch, "walk_in",
        surcharges=surcharges, express=True, date=None, quantity=1,
    )
    # {"pricelist_id": 3, "currency_id": 120, "unit_price": 800.0,
    #  "surcharge_lines": [{"surcharge_id": 1, "product_id": 164, "unit_price": 240.0}],
    #  "express_line": {"product_id": 163, "unit_price": 400.0},   # or None
    #  "total": 1440.0}
    ready = catalog.promised_datetime(service_types_or_products, branch, express=True)
    data = catalog.catalog_for_branch(branch, "pickup", partner=None)  # plain JSON types

* Create one order line per garment line, one per ``surcharge_lines`` entry and
  one for ``express_line``, with the returned unit prices, and keep
  ``pricelist_id`` on the order.
* ``promised_datetime`` counts the turnaround in the plant's working hours
  (``resource_calendar_id.plan_hours``, public holidays included) and returns
  the latest promise of the items, as naive UTC. Without a calendar, plain
  hours. Pass laundry products instead of service types to use the
  per-product turnaround overrides.
* ``catalog_for_branch`` returns the active categories with their sellable
  services, prices, express price and turnaround, and the surcharges that
  apply: ``earlydryer_api`` can return it as is.
* The catalogue generator is also available as
  ``earlydryer.catalog._generate_laundry_products(categories, service_types,
  list_price, taxes, income_account)``.

Configuration
=============

* *Earlydryer > Configuration > Garment Categories / Service Types*.
* *Earlydryer > Configuration > Generate Catalogue*: choose categories and
  service types (all active by default; ``allowed_category_ids`` respected), a
  default price, taxes (none by default) and an income account. Only missing
  combinations are created; existing products, archived ones included, are
  never touched.
* *Earlydryer > Catalogue*: Laundry Services (list grouped by service type, and
  a category × service type pivot of the default price), Retail Products,
  Surcharges, Price Lists, Price Check (workshop tool showing the
  ``price_item`` breakdown and the promised time).
* The *Pricelists* setting (``product.group_product_pricelist``) is enabled on
  install, like *Settings > Sales > Pricelists* does.

Security
========

* Everybody (internal users) reads categories, service types, surcharges,
  products and price lists.
* Only Management (and Earlydryer Administrators) create, edit or delete
  categories, service types, surcharges, laundry / surcharge / express
  products and Earlydryer price lists and their items (access rights plus
  record rules).
* Front Desk cannot change prices. ``earlydryer_base`` gives no Earlydryer role
  below Management ``sales_team.group_sale_manager`` or
  ``product.group_product_manager`` (checked by a test). **But** Branch Manager
  implies ``point_of_sale.group_pos_manager``, which has full access to
  ``product.pricelist`` in core: the record rules of this module block it on
  Earlydryer price lists (non-Earlydryer lists remain editable by POS
  managers, as in core).
* ``auditlog`` rules (create, write, delete) on ``product.pricelist.item``,
  ``earlydryer.surcharge`` and ``earlydryer.service.type``.

Placeholder data
================

Shipped as data (``noupdate``), because the client named them, but to be
confirmed:

* Garment categories: shirt, trouser, agbada, senator, gown, suit, jeans,
  towel, bed sheet, duvet, shoes, travelling box (client) and **suggested**:
  kaftan, 3-piece suit, jacket, skirt, blouse, tie, curtain, rug, bag. Piece
  counts (agbada 3, senator 2, suit 2, 3-piece suit 3) are guesses.
* Service types: wash & fold, wash & iron, dry cleaning, ironing only, stain
  treatment, duvet/curtain cleaning, rug cleaning, shoe cleaning, bag cleaning,
  alterations. **Turnaround hours, express availability, express turnaround
  and surcharges, and allowed categories are placeholders.**
* No sales tax on generated products, surcharges or express (VAT 7.5% only if
  Earlydryer is VAT-registered).

Demo data only: laundry products for every category × allowed service with
fixed walk-in prices for Plant 1, Pickup (+10%) and Plant 2 (+5%) lists
derived from it, a corporate contract (-15%) for *Demo Corporate Client Ltd*,
surcharges (silk 30%, lace 25%, beads ₦1,500, oversized ₦1,000), retail
products (detergent 1 kg, hanger pack, garment bag) and a *Plant 1 Counter*
POS with its price lists synced. All prices are placeholders.

Known issues / Roadmap
======================

* Real price lists per plant and channel, surcharge amounts, express turnaround
  and surcharges, VAT status and the actual garment × service combinations
  are not received yet (open workshop gap).
* Turnaround is counted in **working hours** of the plant calendar: with an
  8-hour day, 72 h means 9 working days. Confirm with Earlydryer whether
  promises are in working hours or calendar hours/days.
* Fixed express amounts are per service type (not per plant or channel).
* The POS front end does not add surcharge and express lines yet:
  ``earlydryer_pos``.

Credits
=======

Authors
-------

* Secteur
