import { patch } from "@web/core/utils/patch";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { OrderSummary } from "@point_of_sale/app/screens/product_screen/order_summary/order_summary";
import { EdIntakePanel } from "@earlydryer_pos/intake/intake_panel";

patch(ProductScreen, {
    components: { ...ProductScreen.components, EdIntakePanel },
});

patch(OrderSummary.prototype, {
    clickLine(ev, orderline) {
        // tapping the selected garment again reopens its details
        if (this.pos.edEnabled && orderline.isSelected() && orderline.edIsGarment) {
            ev.stopPropagation();
            this.numberBuffer.reset();
            return this.pos.edOpenLineDetails(orderline);
        }
        if (this.pos.edEnabled && orderline.edIsLinked && orderline.edParentLine) {
            // linked lines are edited through their garment line
            ev.stopPropagation();
            return this.pos.selectOrderLine(this.currentOrder, orderline.edParentLine);
        }
        return super.clickLine(...arguments);
    },
});
