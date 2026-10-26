import { patch } from "@web/core/utils/patch";
import { Navbar } from "@point_of_sale/app/components/navbar/navbar";

patch(Navbar.prototype, {
    edOpenCollection() {
        this.pos.navigate("EdCollectionScreen");
    },
});
