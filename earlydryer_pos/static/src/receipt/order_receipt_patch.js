import { patch } from "@web/core/utils/patch";
import { OrderReceipt } from "@point_of_sale/app/screens/receipt_screen/receipt/order_receipt";
import { code128DataUrl } from "@earlydryer_pos/receipt/barcode";
import { formatLocal } from "@earlydryer_pos/core/dates";

patch(OrderReceipt.prototype, {
    get edIsLaundry() {
        return Boolean(this.order.config?.earlydryer_enabled && this.order.edIsLaundry);
    },
    get edBranch() {
        return this.order.config?._earlydryer?.branch || {};
    },
    get edBarcode() {
        return code128DataUrl(this.order.pos_reference, { height: 40, width: 1.6 });
    },
    get edCustomer() {
        const partner = this.order.getPartner();
        return {
            name: this.order.earlydryer_new_partner_name || partner?.name || "",
            phone: this.order.earlydryer_new_partner_phone || partner?.phone || "",
        };
    },
    get edPromise() {
        return formatLocal(this.order.earlydryer_promised_estimate, "ccc dd LLL yyyy, HH:mm");
    },
    get edOnAccount() {
        return this.order.payment_ids
            .filter((p) => p.payment_method_id.type === "pay_later")
            .reduce((total, p) => total + p.amount, 0);
    },
    get edPaid() {
        return this.order.payment_ids
            .filter((p) => p.payment_method_id.type !== "pay_later")
            .reduce((total, p) => total + p.amount, 0);
    },
    edLineInfo(line) {
        if (!this.edIsLaundry) {
            return false;
        }
        if (line.edIsLinked) {
            return { linkedTo: line.edParentLine?.getFullProductName() || "" };
        }
        if (!line.edIsGarment) {
            return false;
        }
        return {
            colour: [line.earlydryer_colour, line.earlydryer_brand].filter(Boolean).join(", "),
            condition: line.earlydryer_condition_note || "",
            tags: line.edTagCodes.join(", "),
            untagged: line.edNeedsTags && line.edTagCodes.length < line.edPieceCount,
        };
    },
});
