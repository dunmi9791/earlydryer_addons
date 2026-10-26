===============
Earlydryer Base
===============

Foundation module for the Earlydryer laundry and dry-cleaning business
(Odoo 19.0 Community). Every other ``earlydryer_*`` module depends on it.

It provides:

* **Branches (plants)** – ``earlydryer.branch``: one Odoo company, several
  self-contained plants. Each branch links its address (partner), manager and
  staff, warehouse, points of sale, cash journal, analytic account, operating
  hours and collection shelves. A new plant is pure configuration.
* **Collection shelves** – ``earlydryer.branch.shelf``, with a *Generate
  Shelves* wizard (prefix, start, count, zero padding; existing names are
  skipped).
* **Roles** – security groups with implied groups, so a user needs one or two.
* **Branch security** – record rules restricting users to their allowed
  branches, and a mixin (``earlydryer.branch.mixin``) for later modules.
* **Approvals** – a small engine (``earlydryer.approval.rule``,
  ``earlydryer.approval.request``, ``earlydryer.approval.mixin``) replacing OCA
  ``base_tier_validation``, which does not exist on 19.0.
* **Audit trail** – OCA ``auditlog`` rules (full log of create, write, unlink)
  on branches, approval rules and approval requests.

**Table of contents**

.. contents::
   :local:

Roles
=====

+-------------------------+------------------------------------------+-----------------------------------------------+
| Group (``earlydryer_    | Implies                                  | Standard groups implied                       |
| base.``)                |                                          |                                               |
+=========================+==========================================+===============================================+
| group_front_desk        |                                          | point_of_sale.group_pos_user,                 |
|                         |                                          | stock.group_stock_user                        |
+-------------------------+------------------------------------------+-----------------------------------------------+
| group_production        |                                          |                                               |
+-------------------------+------------------------------------------+-----------------------------------------------+
| group_qc                | group_production                         |                                               |
+-------------------------+------------------------------------------+-----------------------------------------------+
| group_rider             |                                          |                                               |
+-------------------------+------------------------------------------+-----------------------------------------------+
| group_customer_service  |                                          |                                               |
+-------------------------+------------------------------------------+-----------------------------------------------+
| group_branch_manager    | front desk, QC, customer service, rider  | point_of_sale.group_pos_manager               |
+-------------------------+------------------------------------------+-----------------------------------------------+
| group_operations_manager| branch manager, group_all_branches       |                                               |
+-------------------------+------------------------------------------+-----------------------------------------------+
| group_finance           | group_all_branches                       | account.group_account_manager                 |
+-------------------------+------------------------------------------+-----------------------------------------------+
| group_hr                | group_all_branches                       |                                               |
+-------------------------+------------------------------------------+-----------------------------------------------+
| group_management        | operations manager, finance, HR          |                                               |
+-------------------------+------------------------------------------+-----------------------------------------------+
| group_admin             | management                               | base.group_system                             |
+-------------------------+------------------------------------------+-----------------------------------------------+
| group_all_branches      | (technical, not shown as a role)         |                                               |
+-------------------------+------------------------------------------+-----------------------------------------------+

Every role also implies ``base.group_user`` (internal user). The users
``admin`` and ``__system__`` get *Earlydryer Administrator* at install.

On the user form the roles appear in one *Earlydryer* section, as several
dropdowns (Operations, Customer Service, Logistics, Finance, HR, Management),
so a person can be e.g. *Front Desk* and *Rider* at the same time.

The allowed branches and the default branch of a user are set on the
*Earlydryer* page of the user form (Earlydryer Administrators). Users can
change their own default branch in *My Preferences*.

What the groups can do in this module
-------------------------------------

* All internal users read the branches and shelves of their allowed branches;
  ``group_all_branches`` (Operations Manager, Finance, HR, Management) reads all.
* Only Earlydryer Administrators create, edit or delete branches.
* Branch Managers create and edit the shelves of their own branches.
* Approval rules are read by everybody and managed by Management.
* Front Desk cannot edit approval rules and cannot approve requests (unless an
  approval rule names one of their groups as approver).

Usage for later modules
=======================

Branch mixin
------------

::

    class LaundryJob(models.Model):
        _name = "earlydryer.laundry.job"
        _inherit = ["earlydryer.branch.mixin", "mail.thread"]
        _description = "Laundry Job"

        company_id = fields.Many2one(
            "res.company", required=True, default=lambda self: self.env.company
        )

        def _jobs_of_my_branches(self):
            return self.search(self._earlydryer_branch_domain())

``earlydryer_branch_id`` is required, indexed, tracked and defaults to the
user's default branch (or their only allowed branch). The branch company must
match ``company_id`` when the model has one. Inherit ``mail.thread`` too, since
the field is tracked.

The mixin does **not** add security by itself. Add a pair of record rules per
model (``earlydryer_branch_ids`` is available in every rule domain):

::

    <record id="laundry_job_rule_branch" model="ir.rule">
        <field name="name">Laundry job: allowed branches</field>
        <field name="model_id" ref="model_earlydryer_laundry_job"/>
        <field name="domain_force">[('earlydryer_branch_id', 'in', earlydryer_branch_ids)]</field>
        <field name="groups" eval="[(4, ref('base.group_user'))]"/>
    </record>
    <record id="laundry_job_rule_all_branches" model="ir.rule">
        <field name="name">Laundry job: all branches</field>
        <field name="model_id" ref="model_earlydryer_laundry_job"/>
        <field name="domain_force">[(1, '=', 1)]</field>
        <field name="groups" eval="[(4, ref('earlydryer_base.group_all_branches'))]"/>
    </record>

Approval mixin
--------------

::

    class PosOrder(models.Model):
        _name = "pos.order"
        _inherit = ["pos.order", "earlydryer.approval.mixin"]

        def action_earlydryer_apply_discount(self):
            for order in self:
                # raises UserError naming the approver group when needed;
                # self-approves (and logs it) when the rule allows it
                order._earlydryer_approval_ensure("discount", order.discount_pct)
            ...

        def action_earlydryer_ask_discount(self):
            # opens the "Request approval" wizard (reason field)
            return self._earlydryer_approval_wizard_action(
                "discount", self.discount_pct
            )

        def _earlydryer_on_approval_decided(self, request):
            if request.state == "approved":
                ...

Rules are matched per document model, approval type, branch and value: the
active rule with the lowest sequence where ``min_value < value`` and
(``max_value == 0`` or ``value <= max_value``). Rules with branches only apply
to documents of those branches. No matching rule means no approval is needed.
A document passes when an approved request exists for it, the same type and a
value greater than or equal to the current one.

Requests notify (To Do activity) the approver group's users who are allowed on
the document's branch, or all of the group's users when none are. Approve and
Reject are only available to members of the rule's approver group. Requests
can only change state through their buttons (protected fields).

The rule model only uses plain stored fields (``model_name``,
``approval_type``, ``branch_ids``, ``min_value``, ``max_value``,
``approver_group_id``, ``self_approve``), so the offline POS can load the
rules and apply the same matching client side.

Adaptations for Odoo 19
=======================

* Groups use ``res.groups.privilege`` (``privilege_id``) in the category
  ``base.module_category_earlydryer`` created from the manifest category.
  Odoo 19 renders one dropdown per privilege on the user form, so the roles are
  spread over six privileges instead of a single one.
* ``res.users.group_ids`` / ``res.groups.user_ids`` / ``all_group_ids`` are used.
* SQL constraints are ``models.Constraint``; domains use ``odoo.fields.Domain``;
  translations use ``self.env._()``; views use ``<list>``, ``<chatter/>`` and
  Python-expression ``invisible``/``readonly``.
* Record rules cannot read ``user.earlydryer_branch_ids`` on
  ``earlydryer.branch`` itself (reading the many2many applies the same rule
  again). This module adds ``earlydryer_branch_ids`` to the rule evaluation
  context (``ir.rule._eval_context``), read with sudo, like core's
  ``company_ids``.
* Changing allowed branches clears the registry cache (record rule cache):
  ``earlydryer_branch_ids`` is added to ``res.users._get_invalidation_fields``
  and ``earlydryer.branch`` clears it when ``user_ids`` changes.
* OCA ``auditlog`` 19.0 only logs rules in state *confirmed*; the
  ``post_init_hook`` calls ``set_to_confirmed()`` on the shipped rules.
* All standard groups referenced exist in 19.0 under the same XML ids.

Known issues / Roadmap
======================

* Real plant names and codes, discount limits per role, credit approvers and
  staff lists are not configured: demo data only.
* ``auditlog`` is AGPL-3; this module is LGPL-3 and only depends on it.

Credits
=======

Authors
-------

* Secteur
