/* global Sha1 */
import { _t } from "@web/core/l10n/translation";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import { NumberPopup } from "@point_of_sale/app/components/popups/number_popup/number_popup";

/**
 * Approval rules as loaded from the server (earlydryer.approval.rule), matched
 * like earlydryer.approval.rule._earlydryer_match: lowest sequence whose range
 * contains ``value`` (min < value <= max, max 0 = no limit).
 */
export function matchRule(pos, modelName, approvalType, value) {
    return (
        pos.models["earlydryer.approval.rule"]
            .filter(
                (rule) =>
                    rule.model_name === modelName &&
                    rule.approval_type === approvalType &&
                    rule.min_value < value &&
                    (!rule.max_value || value <= rule.max_value)
            )
            .sort((a, b) => a.sequence - b.sequence || a.id - b.id)[0] || false
    );
}

/** Employees of the till who may approve ``rule`` (rule ids computed on the server). */
export function approversOf(pos, rule, fallbackIds = []) {
    const branchId = pos.edBranch.id;
    return pos.models["hr.employee"].filter(
        (employee) =>
            (!employee._earlydryer_branch_id || employee._earlydryer_branch_id === branchId) &&
            (rule
                ? (employee._earlydryer_rule_ids || []).includes(rule.id)
                : fallbackIds.includes(employee.id))
    );
}

/**
 * Ask a manager's PIN, checked against pos_hr's hashed PINs (plain PINs never
 * reach the browser). Returns the approving employee or false.
 */
export async function askManagerPin(pos, approvers, { title, subtitle } = {}) {
    const withPin = approvers.filter((employee) => employee._pin);
    if (!withPin.length) {
        pos.notification.add(_t("No manager with a PIN can approve this on this till."), {
            type: "danger",
        });
        return false;
    }
    const pin = await makeAwaitable(pos.dialog, NumberPopup, {
        title: title || _t("Manager PIN"),
        subtitle: subtitle || withPin.map((employee) => employee.name).join(", "),
        formatDisplayedValue: (x) => x.replace(/./g, "•"),
    });
    if (!pin) {
        return false;
    }
    const hashed = Sha1.hash(pin);
    const employee = withPin.find((e) => e._pin === hashed);
    if (!employee) {
        pos.notification.add(_t("This PIN cannot approve it."), {
            type: "danger",
            title: _t("Wrong PIN"),
        });
        return false;
    }
    return employee;
}
