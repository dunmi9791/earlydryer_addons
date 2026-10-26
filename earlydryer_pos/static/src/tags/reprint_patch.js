import { patch } from "@web/core/utils/patch";
import { ReceiptScreen } from "@point_of_sale/app/screens/receipt_screen/receipt_screen";
import { TicketScreen } from "@point_of_sale/app/screens/ticket_screen/ticket_screen";

patch(ReceiptScreen.prototype, {
    edReprintTags() {
        return this.pos.edPrintTags(this.currentOrder);
    },
});

patch(TicketScreen.prototype, {
    edReprintTags(order) {
        return this.pos.edPrintTags(order);
    },
});
