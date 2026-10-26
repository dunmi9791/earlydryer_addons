import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import {
    approversOf,
    askManagerPin,
    matchRule,
} from "@earlydryer_pos/discount_approval/manager_pin";

patch(PosStore.prototype, {
    restrictLineDiscountChange() {
        // one value per discount (popup), so the approval is asked once
        return this.edEnabled || super.restrictLineDiscountChange(...arguments);
    },

    /**
     * Approval of a ``value`` % discount at the till.
     * :returns: {ok, approver, rule}; no matching rule = core behaviour
     */
    async edApproveDiscount(value) {
        if (!(value > 0)) {
            return { ok: true, approver: false, rule: false };
        }
        const rule = matchRule(this, "pos.order", "discount", value);
        if (!rule) {
            return { ok: true, approver: false, rule: false };
        }
        const cashier = this.getCashier();
        const cashierRules = cashier?._earlydryer_rule_ids || [];
        if (rule.self_approve && cashierRules.includes(rule.id)) {
            return { ok: true, approver: cashier, rule };
        }
        const approvers = approversOf(this, rule).filter(
            (employee) => rule.self_approve || employee.id !== cashier?.id
        );
        const approver = await askManagerPin(this, approvers, {
            title: _t("Discount of %s%% needs approval", value),
        });
        return { ok: Boolean(approver), approver, rule };
    },

    edSetApproval(line, approval) {
        line.earlydryer_discount_approver_employee_id = approval.approver || false;
        line.earlydryer_discount_rule_id = approval.rule || false;
    },

    async setDiscountFromUI(line, val) {
        if (!this.edEnabled) {
            return super.setDiscountFromUI(...arguments);
        }
        if (line.edIsLinked && line.edParentLine) {
            line = line.edParentLine;
        }
        const value = parseFloat(val) || 0;
        const approval = await this.edApproveDiscount(value);
        if (!approval.ok) {
            return;
        }
        this.edSetApproval(line, approval);
        return super.setDiscountFromUI(line, val);
    },

    /** Same discount on every line of the order, approved once. */
    async edSetOrderDiscount(order, value) {
        const approval = await this.edApproveDiscount(value);
        if (!approval.ok) {
            return false;
        }
        for (const line of order.lines.filter((l) => !l.edIsLinked && l.edKind !== "settlement")) {
            this.edSetApproval(line, approval);
            await super.setDiscountFromUI(line, value);
        }
        return true;
    },
});
