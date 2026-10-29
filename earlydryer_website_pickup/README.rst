=========================
Earlydryer Website Pickup
=========================

*Book a Pickup* on the Odoo website, with tracking and cancellation, and
*Pickups* in the customer portal. All the rules live in
``earlydryer.logistics.booking`` (see the *Online booking* section of
``earlydryer_logistics``).

**Table of contents**

.. contents::
   :local:

Website
=======

* ``/pickup`` (menu *Book a Pickup*) works in two server-rendered steps, with
  no JavaScript:

  1. area and first day: shows the free times and the pickup fee;
  2. time, name, phone, address, landmark, gate instructions, note,
     *deliver back* and consent to order messages.

  For logged-in customers, the name, phone and address are filled in.
* Booking redirects to ``/pickup/track?ref=…&token=…``. That page shows the
  status, time, address, fee and the plant's phone, and a *Cancel* button
  while cancelling is allowed.
* *Ask us to call you back* (any area, including areas not served) creates
  a draft pickup and a To Do for Customer Service.
* Each form carries a one-time ``client_ref``, so a double submit books
  once. A hidden honeypot field drops naive bots.

Portal
======

*My Account > Pickups* (``/my/pickups``) lists the customer's pickups (all
sources), with a link to follow the online ones.

Credits
=======

Authors
-------

* Secteur
