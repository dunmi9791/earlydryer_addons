=================
Earlydryer Wallet
=================

A prepaid balance per customer. Customers pay in advance (at the counter, by
bank transfer, later through the website gateway); the money is a **customer
advance** (a liability, not revenue) and is spent on later orders at either
plant: on invoices, on laundry jobs and at the till, online or offline.
Management can credit a wallet (goodwill, claim outcome), and the balances of
the old notebooks are migrated at go-live.

No loyalty points, bonuses or subscriptions. The Community ``loyalty``
eWallet is **not** used: it books top-ups as sales.

Depends on ``earlydryer_pos`` (and through it the other Earlydryer modules)
and ``account``. Later modules build on it: ``earlydryer_payment_gateway``
(online top-ups, ``source = gateway``), ``earlydryer_claims`` (credit as a
claim outcome, ``source = claim``), ``earlydryer_notifications``
(``_earlydryer_on_wallet_transaction_posted``), ``earlydryer_api``
(``earlydryer.wallet.get_balance``).

**Table of contents**

.. contents::
   :local:

Accounting model
================

=========================================  =====================================================
Event                                      Entry
=========================================  =====================================================
Top-up (cash, card, transfer, gateway)     Dr cash / bank outstanding — Cr **Customer advances** (customer)
Wallet spent on an invoice or job          Dr Customer advances (customer) — Cr Receivable (customer), reconciled with the invoice or the job's POS receivable
Wallet spent at the till                   Dr Customer advances (customer) — Cr the POS sale, at session closing (Wallet payment method)
Top-up sold at the till                    Dr cash (session) — Cr Customer advances (customer), at session closing
Refund to the customer                     Dr Customer advances (customer) — Cr cash / bank outstanding
Goodwill or claim credit                   Dr Claims and goodwill (expense, configurable) — Cr Customer advances (customer)
Migration of old balances                  Dr Opening balance account (configurable) — Cr Customer advances, one line per customer
Correction                                 Reversal of the original entry, never an edit
=========================================  =====================================================

* Customer advances is a current-liability account that allows reconciliation
  and is used for nothing else.
* Every entry built here goes through ``_earlydryer_prepare_move_vals()``
  (spends, credits, migration) or ``_earlydryer_prepare_payment_vals()``
  (top-ups and refunds are ``account.payment`` records). Till transactions
  have no entry of their own: the session closing entry carries them.
* **Top-ups and refunds are account.payment records** with the destination
  account set to Customer advances: in Odoo 19 ``destination_account_id`` is
  stored and writable, so no transfer entry from the receivable is needed.
  Cash journals post straight to the journal's cash account
  (``force_outstanding_account_id`` of ``point_of_sale``); bank and card
  journals post to Outstanding Receipts as any customer payment, matched with
  the bank statement as usual.
* **VAT**: a top-up is not a sale and carries no tax (the top-up product has
  none). If Earlydryer is VAT-registered (still unconfirmed), VAT arises on
  the invoice or POS sale when the wallet is spent, with the normal taxes of
  the products sold.

Subledger and general ledger
----------------------------

The wallet ledger (``earlydryer.wallet.transaction``) is the **subledger of
record** of each customer's balance. Partners are on every Customer advances
line Odoo allows (all of them in practice: the wallet payment method
identifies the customer), but the control is global: the general-ledger
balance of Customer advances must equal the **sum of all wallet balances**.

*Wallets > Wallet Control* (Finance and above) shows, for a date, the sum of
the wallets, the GL balance, the difference, the till transactions whose
session is not closed yet (the usual timing difference: the wallet moves at
the sale, the GL at the closing) and the unexplained rest, plus the overdrawn
wallets. After every session is closed the difference is 0.

Setup
=====

1. **Accounts and journal** are created on install for every company with a
   chart (and when a chart is loaded later), with XML ids
   ``earlydryer_wallet.<company id>_wallet_*`` so they survive chart changes:
   *Customer Advances (Wallet)* (current liability, reconcilable, proposed
   code 2130), *Claims and Goodwill* (expense, 6500), journal *Wallet* (WAL,
   miscellaneous). The opening account defaults to the company's undistributed
   profits account (``get_unaffected_earnings_account``). The proposed codes
   are system parameters (``earlydryer_wallet.*_code``), never Python; the
   next free code is used when taken. **Placeholders** until the accountant
   chooses.
2. **Settings > Earlydryer > Wallet** (Finance, Administrator): the four
   accounts and journal, *Apply Wallet to Invoices* (off by default) and the
   *Minimum Top-up* (0).
3. **POS payment method** *Wallet*: created on install for each company with
   an Earlydryer till: no journal (Odoo 19 type ``pay_later``), *Identify
   Customer* (``split_transactions``), ``earlydryer_is_wallet``. Add it to a
   till with **Add Wallet Payment** on the till form (never added silently).
4. **Top-up product** *Wallet Top-up* (``earlydryer_kind = wallet_topup``, no
   tax, income account Customer advances per company), in the POS category
   *Extras*.

Using the wallet
================

Backend
-------

* **Customer form**: a *Wallet* smart button with the balance (opens the
  wallet and its transactions), *Top Up Wallet*, *Refund Wallet*, *Credit
  Wallet* and *Wallet Statement* (QWeb PDF for a date range: opening balance,
  transactions, closing balance).
* **Top-up**: amount (at least the minimum), journal (cash journal of the
  user's plant by default, or a bank/card journal), plant, reference.
* **Refund**: at most the balance, journal, reason; goes through approval.
* **Credit**: amount, reason, optional laundry job and claim reference; goes
  through approval.
* **Pay from Wallet** on posted customer invoices with a residual (amount:
  the smaller of the residual and the balance) and on laundry jobs with an
  amount due (sales flow: the job's open invoice; POS job on the customer
  account: its pay-later receivable, reconciled now, or at the session closing
  if the session is still open). The job form shows the wallet balance next
  to the amount due.
* **Apply Wallet to Invoices**: when set, posting a customer invoice from a
  sales order (laundry jobs are invoiced through their sales order) spends the
  available balance on it. Never on POS invoices nor plain invoices. A failure
  never blocks the posting (logged).
* Posted transactions are never edited or deleted. **Reverse** (Finance and
  above, reason required) posts the reversal entry of the original (a spend
  gives the invoice its residual back) and restores the balance. Till
  transactions have no entry of their own: correct them at the till with a
  refund. A wallet can be **blocked** by Finance: no spend or top-up, refund
  still possible by Finance.
* **No negative balance**: a spend, refund or reversal beyond the balance is
  refused. Posting locks the wallet row (``SELECT ... FOR NO KEY UPDATE``,
  waiting rather than failing) and reads the posted balance from the
  database, so two tills or users cannot overdraw it together.

Laundry jobs
------------

``laundry.job._earlydryer_extra_paid()`` counts only wallet spends on the job
**not yet reconciled** with its receivable: a spend on a POS job whose session
is still open (its receivable does not exist until the closing). Every other
spend is reconciled with the invoice or the POS receivable at once, which
already lowers the due amount, so it is never counted twice (tests cover both
the sales flow and the POS flow, before and after the closing).

Approvals
=========

``approval_type`` gains *Wallet Refund* and *Wallet Credit*
(``selection_add``). Shipped rules (``noupdate``), **placeholders** until
Earlydryer decides:

* refunds of any amount: **Management** (no self-approval: another manager
  approves);
* credits up to ₦10,000: **Branch Manager** (self-approval allowed);
* credits above ₦10,000: **Management**.

Refunds and credits stay **draft** until ``_earlydryer_approval_ensure``
passes; the approval (``_earlydryer_on_approval_decided``) posts them, a
rejection cancels them. If the balance was spent while the refund waited, the
approval is kept, the refund stays draft and a note explains why.

Point of sale
=============

* **Wallet method**: the till needs a real customer (not the walk-in) and
  caps the amount at the known balance less the wallet payments made on this
  till since the balance was loaded. The session loads the non-zero balances
  only (``config._earlydryer_wallet``); ``earlydryer.wallet.get_balance``
  refreshes one customer when chosen and when the Wallet method is clicked
  (online only, 4 s at most). Wallet payments validated on the till are kept
  in ``localStorage`` (like the tag counters) until the server confirms it has
  their order.
* **Top-up at the counter**: sell *Wallet Top-up* at the amount paid; it needs
  a real customer and cannot be discounted.
* **Receipt**: when the customer has a wallet, *Wallet balance (as at time of
  sale)* after the order (``earlydryer_wallet_balance_after``, as the till
  knew it).
* ``earlydryer_pos`` amounts: wallet payments count as **paid**, not as a
  customer-account balance (``_earlydryer_pay_later_amount``, receipt
  *Balance due*); the wallet method never counts as the till's *Customer
  Account* method.

Sync and accounting
-------------------

``pos.order._process_saved_order``, in its own savepoint (a failure is stored
in *Wallet Sync Error*, Finance and the branch manager get an activity,
*Retry Wallet Sync* replays it; the sale is never lost):

* each wallet payment line: a posted ``spend`` (source *pos*, order,
  employee, plant, job) without an entry; a negative wallet payment (refund
  paid back to the wallet) reverses the refunded order's spend;
* each top-up line: a posted ``topup`` without an entry; a refunded top-up
  line creates the ``reversal`` of the original top-up;
* idempotent: one transaction per POS payment or line (unique indexes).

At closing (Odoo 19 posts journal-less methods per customer when *Identify
Customer* is set), ``pos.session`` sends:

* wallet payments to **Customer advances** with the customer
  (``_get_split_receivable_vals``) instead of the receivable, excluded from
  follow-ups;
* top-up lines to **Customer advances** with the customer (``_get_sale_key``
  / ``_get_sale_vals``, as the balance settlements of ``earlydryer_pos``), not
  to revenue.

Observed closing entry of a session with a wallet payment of ₦2,000 (Emeka)
and a top-up of ₦5,000 (Grace) in demo::

    Dr Customer Advances (Wallet)  2,000   Emeka Obi     "<session> - Wallet"
    Cr Customer Advances (Wallet)  5,000   Grace Adeyemi "Wallet top-up"
    Cr Sales ...                   (the goods)          Dr Cash ...

**Invoiced POS orders**: Odoo 19 creates no entry for journal-less payments of
an invoiced order. While the session is open, each wallet payment of an
invoiced order gets an entry Dr Customer advances / Cr receivable in the POS
journal, reconciled with the invoice by core. After the closing, core's
reversal entry already settles the invoice and the closing entry keeps the
debit on Customer advances.

Offline and overdraw
--------------------

Offline, a till only knows the balances loaded with the session and its own
wallet payments. Two tills offline can spend the same balance. At sync the
spend is **recorded, never refused**: it is posted, flagged **Overdrawn** with
its shortfall (transaction and wallet), Finance and the branch manager get an
activity, and the wallet shows a negative balance until Finance recovers the
difference from the customer (top-up) or decides otherwise. Blocked wallets
are refused at the till when known; a till offline may still accept one (the
sale stands).

Migration
=========

*Wallets > Import Wallet Balances* (Finance, Administrator). CSV or XLSX, one
row per customer:

===============  ========  ==============================================================================
Column           Required  Content
===============  ========  ==============================================================================
``ref``          yes       Unique reference of the balance (notebook line); re-imports skip it
``name``         yes*      Customer name
``phone``        yes*      Phone; Nigerian numbers normalised (``0803…``, ``803…``, ``234…`` → ``+234…``)
``balance``      yes       Amount owed to the customer (≥ 0; ``1,500``, ``₦1500`` accepted)
``branch_code``  no        Plant code (reporting)
``note``         no        Free text, kept as the reference
===============  ========  ==============================================================================

\* name or phone. Plus the *as-of* date (date of the transactions and of the
entry).

Matching: normalised phone, then exact name, else a new customer. **Dry run
first** (matched, new, skipped, errors, total); nothing is written until
*Confirm and Post*. Each row becomes one ``migration`` transaction
(``import_ref``, unique per company), with **one summary entry** per import
(Dr opening account for the total, Cr Customer advances one line per
customer). Negative balances (customers who owe Earlydryer) are refused: they
belong in the opening receivables, done in accounting.

Reports
=======

* *Wallets > Wallet Balances*: balance, last transaction, phone, plant of the
  last top-up; pivot by plant; standard export (``report_xlsx`` was not worth
  a dependency for a list).
* *Wallets > Transactions*: filters by type, source, plant, overdrawn, date;
  group by user, POS employee, customer, plant.
* *Wallets > Wallet Control* (Finance and above), see above.

Security
========

Enforced in Python (``earlydryer.wallet._earlydryer_check_right``), not only
in views. Wallets and transactions are readable by every internal user
(customers use both plants: no plant rule) and written only through the
model methods (direct create/write is refused).

==================  =======  ==================  ========  ==================  ==================  =======  ======  =======
Group               View     Top up              Spend     Refund              Credit              Reverse  Import  Control
==================  =======  ==================  ========  ==================  ==================  =======  ======  =======
Front Desk          yes      own plant cash      yes       request             no                  no       no      no
Customer Service    yes      no                  no        request             request             no       no      no
Branch Manager      yes      yes                 yes       request             request / approve   no       no      no
Finance             yes      yes                 yes       request             request             yes      yes     yes
Management          yes      yes                 yes       approve             approve             yes      yes     yes
Administrator       full     full                full      full                full                full     full    full
==================  =======  ==================  ========  ==================  ==================  =======  ======  =======

Who approves follows the approval rules (above). Finance alone is not in the
shipped approver groups; give Finance a rule if it should approve. ``auditlog``
logs every create and write of wallet transactions, and writes on
``res.company`` where the wallet settings live (auditlog allows one rule per
model: an existing company rule is reused with writes switched on).

Odoo 19 notes and deviations
============================

* **Payments**: ``account.payment`` with ``destination_account_id`` =
  Customer advances (no receivable-to-advances transfer). Cash posts to the
  cash account directly; bank and card to Outstanding Receipts (standard 19
  flow, matched with the statement).
* **Journal-less POS method**: Odoo 19 posts it per customer to the
  customer's receivable (``_get_split_receivable_vals``) or, combined, to
  ``_get_receivable_account``; both are redirected to Customer advances for
  wallet methods. ``receivable_account_id`` is left empty: its domain only
  offers receivable accounts.
* **Row lock**: plain ``SELECT ... FOR NO KEY UPDATE`` (waits);
  ``lock_for_update()`` of 19 uses ``SKIP LOCKED`` and would fail the second
  till instead of serialising it.
* Extra fields beyond the brief: ``pos_payment_id`` / ``pos_order_line_id``
  on transactions (idempotent sync), ``overdrawn`` / ``shortfall``,
  ``earlydryer_wallet_balance_after`` and ``earlydryer_wallet_error`` on POS
  orders.
* A reversal of a till transaction is done at the till (POS refund), not in
  the backend: it has no entry of its own to reverse.
* Tours need Chrome, missing in the official ``odoo:19`` image (see
  ``earlydryer_pos``): the till behaviour is covered by server tests and the
  manual checks.

Open questions for Earlydryer and its accountant
================================================

* Can wallet balances be refunded in cash, and who approves (placeholder:
  Management, any amount)?
* Credit approval limits (placeholder: Branch Manager up to ₦10,000,
  Management above).
* Do balances ever expire?
* Minimum top-up (default 0)?
* The migration list of customer balances and its as-of date.
* Name and code of the customer advances account (placeholder 2130
  *Customer Advances (Wallet)*), and of the goodwill expense (6500).
* VAT registration status.

Credits
=======

Authors
-------

* Secteur
