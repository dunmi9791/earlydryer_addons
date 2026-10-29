================================
Earlydryer Accounting (Nigeria)
================================

Earlydryer's books for Nigeria and for two plants on one company: chart
additions and journals per plant, the VAT switch, withholding tax (WHT) on
vendor bills and on customer invoices, analytics by plant and by service
line, the invoice layout with the TIN, the daily cash-up and bank lodgement,
fiscal year and lock dates, the month-end checklist and the opening balances.

It is mostly **configuration delivered as code**: a setup wizard, data and
small extensions. Ledgers, aged balances, assets, lock dates, bank statement
import and reconciliation come from the OCA modules it depends on.

.. warning::

   **Every tax rate and account code in this module is a PLACEHOLDER** until
   Earlydryer's accountant or tax adviser confirms it. They are data or
   ``ir.config_parameter`` values, never Python constants, and are listed in
   `Placeholders to confirm`_.

**Table of contents**

.. contents::
   :local:

Nigerian localisation
=====================

Odoo 19 Community ships ``l10n_ng`` (Nigeria - Accounting). It copies the
generic chart (same codes) and adds VAT 7.5% / 0% / exempt sales and purchase
taxes, 5% and 10% withholding taxes, a domestic and an import fiscal position
and a VAT report. **Recommended:** create Earlydryer's company with country
Nigeria, so that ``l10n_ng`` is installed and its chart is used. It is not a
dependency of this module (the chart is chosen when the company is created);
the module works on the generic chart too.

With the Nigerian chart the setup **reuses** l10n_ng's 7.5% taxes and its Tax
Received / Tax Paid accounts. With any other chart it creates VAT 7.5% taxes
in an "Earlydryer VAT" tax group.

Running the setup
=================

*Settings > Earlydryer > Accounting (Nigeria) > Run accounting setup*, or
*Accounting > Earlydryer > Configuration > Run Accounting Setup* (Finance or
Administrator).

1. **Options:** the bank and account number of a real bank account, the card
   terminal providers (comma-separated), whether discounts get their own
   account, the bank used for transfers at the counter.
2. **Preview:** every account and journal, marked *Exists: reused* or *Will
   be created*. Codes and names of the records to create can be edited.
3. **Confirm:** creates only what is missing and shows what it did, with a
   table of the POS payment methods.

The wizard is idempotent. Records are found by XML id first
(``earlydryer_accounting_ng.<company id>_<key>``), then by code. Everything
it creates gets such an XML id, so running it again creates nothing. Run it
again after adding a plant, a bank account or a card provider.

Accounts and journals
=====================

Accounts (proposed codes follow the generic chart that l10n_ng copies):

=====================================  ============================  =========  ===============================
Account                                Type                          Reconcile  Proposed code / origin
=====================================  ============================  =========  ===============================
Laundry service revenue                Income                        no         401000
Retail sales revenue                   Income                        no         402000
Delivery fee revenue                   Income                        no         403000
Sales discounts (optional)             Income                        no         409000
Cost of retail goods sold              Cost of revenue               no         501000
Laundry consumables                    Cost of revenue               no         502000
Claims and goodwill                    Expense                       no         earlydryer_wallet's account
Cash over and short                    Expense                       no         644000
Cash at plant (one per plant)          Bank and cash                 no         101510, 101511... or the plant's cash journal account
Card terminal clearing (per provider)  Current assets                yes        105100, 105101...
Rider cash in transit (per plant)      Current assets                yes        105200, 105201...
Payment gateway clearing               Current assets                yes        105300
Cash in transit to bank                Current assets                yes        105400
Customer advances                      Current liabilities           yes        earlydryer_wallet's account: **reused, never duplicated**
VAT output / VAT input                 Current liability / asset     no         the chart's Tax Received / Tax Paid (l10n_ng's on the Nigerian chart)
WHT payable                            Current liabilities           yes        253000
WHT receivable                         Current assets                yes        133000
Opening balance equity                 Equity (undistributed)        no         the company's undistributed profits account
=====================================  ============================  =========  ===============================

Income accounts by product kind: products of kind ``laundry``, ``surcharge``
and ``express`` without an income account of their own post to Laundry
service revenue, ``retail`` to Retail sales (and Cost of retail goods sold).
Products of the *Delivery Fees* category (for the logistics module) post to
Delivery fee revenue. ``settlement`` and ``wallet_topup`` keep the accounts
their modules set. This is a fallback in ``product.template._get_product_accounts``,
so new products need no setting.

Journals:

======================  =======  ==============  ===============================================
Journal                 Type     Scope           Notes
======================  =======  ==============  ===============================================
``<plant>`` Cash        cash     one per plant   ``earlydryer.branch.cash_journal_id``; cash differences go to Cash over and short
``<plant>`` Rider Cash  cash     one per plant   rider collections before handover (logistics module)
Card Clearing           bank     company         one per provider; receipts go to the clearing account
Bank                    bank     company         one per real bank account; shown on invoices
Payment Gateway         bank     company         for earlydryer_payment_gateway
Wallet                  general  company         earlydryer_wallet's, reused
Opening Balances        general  company         used only by the opening balance import
======================  =======  ==============  ===============================================

**Why bank and card journals are company-wide.** One real bank account or
card terminal contract serves both plants, and reconciliation works per real
account. Plant journals exist only for the plants' cash. Profit per plant
comes from the analytics, not from separate bank journals.
``account.journal.earlydryer_branch_id`` is set on plant journals and empty
on company-wide ones; Front Desk and Branch Managers only see the cash
journals of their plants (record rule).

POS payment methods: for each Earlydryer till the setup links a cash method
on the plant's cash journal, a card method on the card clearing journal and
a bank transfer method on the chosen bank. Customer Account and Wallet
methods are left as their modules made them. A method replaced on a till is
unlinked from it, never deleted. Tills with an open session are skipped.

Fiscal year: ends 31 December. The OCA fiscal years of the current and next
year and 24 monthly periods (``date.range``) are created.

VAT
===

*Settings > Earlydryer > Accounting (Nigeria)*:

* **VAT Registered** (default off, still unconfirmed) and **Prices Include
  VAT** (default on: walk-in prices are quoted VAT-inclusive, to confirm).
* **Apply VAT setting** (also run by the setup):

  * registered: the sales VAT goes on every laundry, surcharge, express,
    retail and delivery product, and becomes the default sales and purchase
    tax;
  * not registered: the sales VAT is taken off those products and the
    default taxes are cleared.

* Two sales taxes exist, price-included and price-excluded, so switching
  never changes a tax already used on documents.
* Purchase VAT is put on vendor bills by hand when the vendor charges VAT.
* The tills take the product taxes; reopen a session to load them.

**Effects:** only new documents. Posted invoices are never touched, and
open orders keep their taxes. A warning shows when documents were already
issued. Invoices print VAT lines only when there is VAT.

Withholding tax
===============

Payable (vendor bills)
----------------------

* WHT categories (*Accounting > Earlydryer > Withholding Tax > WHT
  Categories*, Finance) have a rate for company vendors and one for
  individuals. Each rate becomes a purchase tax with a negative amount
  posting to WHT payable. A rate change on a tax already used creates a new
  tax and archives the old one.
* Vendors get a WHT category and a vendor type (*Accounting* tab). Bill lines
  take the vendor's WHT tax by default.
* The bill total is net: the vendor is paid net, and WHT payable holds the
  tax authority's share. The WHT shows on the bill, the payment and the
  payment advice. Credit notes reverse it.
* **Remove WHT** (draft bill, Finance) takes it off lines, e.g. for exempt
  goods, with the reason logged in the chatter. Removing it any other way is
  refused.
* **WHT Remittance** (period, PDF and XLSX): vendor, TIN (partner's Tax ID),
  invoice, date, gross, rate, WHT, category. **Mark Remitted** creates the
  payment to the tax authority from the chosen bank and reconciles the WHT
  payable lines.

**Why not Odoo's "Withhold on Payment"** (``l10n_account_withholding_tax``,
Community): it computes withholding only when a payment is registered through
the payment wizard. Bills paid by reconciling the bank statement, which is the
main flow here (``account_reconcile_oca``), would skip it. It also does not
show the WHT or the net amount on the bill. The negative-tax approach is the
one ``l10n_ng`` itself uses for its WH taxes.

Receivable (deducted by corporate customers)
--------------------------------------------

**Register WHT Deduction** on a posted customer invoice (Finance) posts
Dr WHT receivable / Cr Receivable, reconciled with the invoice. It records the
customer's credit note or certificate reference.
*WHT Awaiting Certificates* lists the deductions until *WHT Certificate
Received* is pressed.

Analytics
=========

Two plans:

* **Plants:** one analytic account per plant. The plant accounts of
  ``earlydryer_base`` are reused and moved into this plan.
* **Service Lines:** Wash and Iron, Dry Cleaning, Ironing Only, Household
  Items, Shoes and Bags, Alterations, Retail, Delivery, Corporate Contracts
  (optional: archive it if not needed). Service types map to a line (default
  mapping shipped, editable). Retail products default to Retail, and the
  Delivery Fees category to Delivery.

How lines get their distribution:

* **Distribution models** get two criteria, plant and service line. The setup
  creates one model per plant and one per service line, and core merges one
  model per plan. Invoice lines take the plant of the document
  (``account.move.earlydryer_branch_id``: from the sales order, the POS
  session, the journal or the user's default plant) and the service line of
  the product. Sales order lines do the same, and so do bills (the plant is
  picked on the bill; service line optional).
* **POS override:** Odoo 19 groups a session's sales in
  ``pos.session._get_sale_key`` without analytics. The key gets the order
  line's distribution, made of the till's plant plus the product's service
  line (or the garment line's, for surcharge and express lines), and
  ``_get_sale_vals`` sets it on the line. Revenue is split by service line,
  and every line carries the plant. All entries created while closing are
  marked with the plant, so their cash and receivable lines take the plant
  through the models.
* **Analytic Gaps** (*Accounting > Earlydryer*): posted income and expense
  lines without a plant. It is a warning list, never a block. The month-end
  checklist checks it.

Cash-up and lodgement
=====================

The daily routine at each plant:

1. Close the POS session. Odoo counts the cash, and differences post to Cash
   over and short.
2. **Cash Lodgement** (plant form, or *Accounting > Earlydryer*): the amount
   defaults to the plant cash balance minus the plant's float
   (``earlydryer_cash_float``, placeholder). It posts Dr Cash in transit /
   Cr Plant cash, with the teller slip reference. Branch Managers lodge
   their plants and Finance any plant. Leaving less than the float in the
   till needs a Branch Manager of the plant or Management. Front Desk does
   not lodge.
3. When the bank statement is imported (``account_statement_import_sheet_file``),
   its line is reconciled with Cash in transit.

**Rider handover:** ``account.move._earlydryer_rider_handover(branch,
amount, rider_employee)`` posts Dr Plant cash / Cr Rider cash in transit (the
*Rider Cash Handover* wizard calls it). It is meant for the logistics module.

**Daily cash report** (PDF, per plant): opening cash, POS cash takings (of
which settlements and wallet top-ups), rider handovers, lodgements, cash
differences, closing cash and float, and the non-cash takings by method with
order counts. It reads only the posted entries of the plant cash account and
the POS payments. ``earlydryer.branch.action_earlydryer_daily_cash_report(date)``
returns the PDF for the notifications module.

Opening balances
================

*Accounting > Earlydryer > Configuration > Import Opening Balances* (Finance
and Administrator). A CSV or XLSX trial balance at the cut-over date:

=================  ========  ========================================================
Column             Required  Content
=================  ========  ========================================================
``account_code``   yes       code of an existing account
``account_name``   yes       checked against the chart, for information only
``debit``          yes       positive amount or empty
``credit``         yes       positive amount or empty
``partner_ref``    AR/AP     phone (Nigerian, normalised), then partner reference, then exact name
``plant_code``     no        plant code: the line gets the plant analytic
``label``          no        line label
``date_maturity``  no        due date (YYYY-MM-DD or DD/MM/YYYY), so ageing works
=================  ========  ========================================================

* **Dry Run first:** it checks debits against credits, account codes and
  partners, posts nothing, and stops on errors.
* **Customer advances rows are refused.** Wallet balances come in through
  the wallet import (earlydryer_wallet), which posts them itself. The wizard
  shows the file's advances figure next to the wallet import total, so the
  accountant can check they agree.
* **Posting:** one entry in the Opening Balances journal on the cut-over
  date, with receivable and payable lines per partner and due dates. A
  difference goes to Opening balance equity only when confirmed.
* A second import for the same date is refused until the earlier entry is
  reversed.

``demo/opening_trial_balance.csv`` is a sample file (demo database).

Month-end checklist
===================

*Accounting > Earlydryer > Month-end Checklist* (Finance; Management reads).
One checklist per period, with steps the accountant ticks. Most steps have a
**Check** button:

=============================================  ==================================================
Step                                           Automatic check
=============================================  ==================================================
All POS sessions closed                        sessions opened up to the period end and not closed
Bank statements imported and reconciled        unreconciled bank statement lines
Card and gateway clearing reconciled           unreconciled lines on card, gateway, rider and in-transit accounts
Wallet control difference zero                 earlydryer_wallet's control report (unexplained difference)
Analytic gaps empty                            income and expense lines without a plant
WHT remittance prepared                        WHT payable not remitted
Depreciation posted                            unposted depreciation lines (account_asset_management)
VAT return prepared (if registered)            not applicable when not registered; tax lock date
Lock date set                                  lock dates; **Open** starts the account_lock_date_update wizard
=============================================  ==================================================

Reports
=======

*Accounting > Earlydryer > Reports*:

* trial balance, general ledger, open items and aged balances
  (``account_financial_report``, menu shortcuts only);
* MIS Builder: the *Earlydryer P&L* template (by account type, so it works
  on any chart) with the instances **P&L by Plant** and **P&L by Service
  Line**, one column per analytic account plus a total. The *Cash Flow
  Summary* shows cash and bank movements by journal type. The setup creates
  the instances.

The WHT reports, the daily cash report, Analytic Gaps and the customer
statement (*Print > Customer Statement* on a contact: invoices, payments,
wallet balance and ageing; reused by the corporate module) are described
above.

Invoice layout
==============

The customer invoice and credit note template is inherited, not copied. It
adds:

* company name, RC number (``company_registry``) and TIN (``vat``);
* the plant's name, address and phone;
* the laundry job numbers and item count;
* the bank accounts of the bank journals marked *Show on Invoices*;
* the footer note (setting).

Vendor bills and payment advices show the WHT deducted.

Security
========

No new group. ``earlydryer_base`` maps Finance to ``account.group_account_manager``
and gives Branch Managers POS Manager. Accounting access is not widened
here. The rights below are enforced in Python (the wizards post with sudo
after the check):

.. list-table::
   :header-rows: 1

   * - Role
     - Setup, VAT, import
     - Taxes and WHT
     - Lodgement
     - Rider handover
     - Cash report
     - Checklist
     - Reports
   * - Front Desk
     - no
     - no
     - no
     - no
     - own plant
     - no
     - no
   * - Branch Manager
     - no
     - no
     - own plant
     - own plant
     - own plant
     - no
     - plant P&L needs Finance
   * - Finance
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
     - yes
   * - Management
     - as Finance
     - as Finance
     - float exceptions
     - yes
     - yes
     - yes
     - yes
   * - Administrator
     - full
     - full
     - full
     - full
     - full
     - full
     - full

Management implies Finance in ``earlydryer_base``, so it gets Finance's
rights, write included. Audit logs (auditlog, create and write) are kept on
taxes, accounts, WHT categories and the company (tax settings).

Placeholders to confirm
=======================

* **VAT** rate 7.5% (``earlydryer_accounting_ng.vat_rate``), the
  registration status and whether prices include VAT.
* **WHT** rates (company / individual): professional and consultancy 10/5,
  technical and management 10/5, rent 10/10, construction and contracts 5/5,
  commission 10/5, supply of goods 5/5 (inactive: often exempt). Also which
  vendors are exempt.
* **Account codes** (``earlydryer_accounting_ng.code_*`` parameters, see
  `Accounts and journals`_) and journal codes (``journal_code_*``).
* **Float per plant** (``earlydryer.branch.earlydryer_cash_float``).
* **Tax authority** partner of the remittances.

FIRS e-invoicing (held)
=======================

Not built, pending Earlydryer's tax status and the FIRS requirements.
Extension point: ``res.company.earlydryer_einvoice_enabled`` (default off,
visible in debug mode). When it is on, posting customer invoices and credit
notes calls ``account.move._earlydryer_einvoice_submit()``, an empty hook for
a later module. No IRN or QR fields are created.

Credits
=======

Authors
-------

* Secteur
