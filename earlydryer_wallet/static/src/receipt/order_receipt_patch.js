import { patch } from "@web/core/utils/patch";
import { OrderReceipt } from "@point_of_sale/app/screens/receipt_screen/receipt/order_receipt";

patch(OrderReceipt.prototype, {
    get edOnAccount() {
        // wallet payments are paid, not a balance on account
        return this.order.payment_ids
            .filter((p) => p.payment_method_id.type === "pay_later")
            .filter((p) => !p.payment_method_id.earlydryer_is_wallet)
            .reduce((total, p) => total + p.amount, 0);
    },
    get edPaid() {
        return this.order.payment_ids
            .filter(
                (p) =>
                    p.payment_method_id.type !== "pay_later" ||
                    p.payment_method_id.earlydryer_is_wallet
            )
            .reduce((total, p) => total + p.amount, 0);
    },
    get edWalletBalance() {
        const value = this.order.earlydryer_wallet_balance_after;
        return typeof value === "number" && this.order.getPartner() ? value : false;
    },
});
