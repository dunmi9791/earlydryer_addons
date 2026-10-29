==============
Earlydryer API
==============

REST API (OCA ``fastapi``) for the Earlydryer website and mobile app. It
covers online pickup booking and is a thin layer over
``earlydryer.logistics.booking`` (see the *Online booking* section of
``earlydryer_logistics``): all the rules live there.

**Table of contents**

.. contents::
   :local:

Setup
=====

* On install, the endpoint *Earlydryer API* is created at
  ``/earlydryer/api/v1``. It runs as the technical user *Earlydryer API*,
  which has no rights of its own.
* *Settings > Technical > FastAPI > Endpoints > Earlydryer API*: the
  **API key** (generated on install, visible to administrators) goes to the
  app developers. The app sends it in the ``X-Api-Key`` header. *New API
  Key* replaces it at once. With an empty key, every request is refused.
* Python: ``fastapi``, ``pydantic``, ``a2wsgi`` and the other requirements
  of the OCA ``fastapi`` module.

Routes
======

==========================================  ==========================================
``GET  /areas``                             areas served (address picker)
``POST /pickups/quote``                     fee and free times for an area
``POST /pickups``                           book on a slot from the quote (201);
                                            scheduled at once
``POST /pickups/callback``                  area not served or no time suits:
                                            Customer Service calls back (201)
``GET  /pickups/{reference}?token=``        follow a pickup
``POST /pickups/{reference}/cancel?token=`` cancel (before the slot's cut-off)
==========================================  ==========================================

Pickup references contain slashes (``P1/STP/00031``) and are used as they
are in the path. Errors:

* ``401``: bad or missing API key;
* ``400``: business refusal, with the message to show in ``detail``
  (area not served, slot taken, too many open pickups, invalid phone);
* ``422``: malformed input.

The OpenAPI documentation is at ``/earlydryer/api/v1/docs``.

Send a ``client_ref`` (a UUID per booking attempt): retrying with the same
key returns the same pickup instead of booking twice.

Credits
=======

Authors
-------

* Secteur
