import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { PosOrderline } from "@point_of_sale/app/models/pos_order_line";
import { estimatePromise } from "@earlydryer_pos/core/promise_estimate";

const { DateTime } = luxon;

// set while the laundry code itself changes linked lines
let internalChange = 0;
export function edInternal(fn) {
    internalChange += 1;
    try {
        return fn();
    } finally {
        internalChange -= 1;
    }
}

patch(PosOrderline.prototype, {
    get edKind() {
        return this.product_id?.product_tmpl_id?.earlydryer_kind || false;
    },
    get edIsGarment() {
        return this.edKind === "laundry";
    },
    /** Surcharge or express line attached to a garment line. */
    get edIsLinked() {
        return Boolean(this.earlydryer_parent_line_uuid);
    },
    get edParentLine() {
        return this.edIsLinked
            ? this.order_id?.lines.find((line) => line.uuid === this.earlydryer_parent_line_uuid)
            : false;
    },
    get edChildLines() {
        return (this.order_id?.lines || []).filter(
            (line) => line.earlydryer_parent_line_uuid === this.uuid
        );
    },
    get edService() {
        return this.product_id?.product_tmpl_id?.earlydryer_service_type_id || false;
    },
    get edCategory() {
        return this.product_id?.product_tmpl_id?.earlydryer_garment_category_id || false;
    },
    /** Pieces (and so tags) of the line: quantity × pieces of the garment. */
    get edPieceCount() {
        return this.edIsGarment
            ? Math.max(Math.round(this.qty), 0) * (this.edCategory?.piece_count || 1)
            : 0;
    },
    get edNeedsTags() {
        return this.edIsGarment && Boolean(this.edService?.requires_tag);
    },
    get edTagCodes() {
        return (this.earlydryer_tag_codes || "")
            .split(",")
            .map((code) => code.trim())
            .filter(Boolean);
    },
    get edSurchargeIds() {
        return this.edChildLines
            .filter((line) => line.earlydryer_surcharge_id)
            .map((line) => line.earlydryer_surcharge_id.id);
    },
    get edHasExpress() {
        return this.edChildLines.some((line) => line.edKind === "express");
    },

    canBeMergedWith(orderline) {
        if (
            this.edKind ||
            orderline.product_id?.product_tmpl_id?.earlydryer_kind ||
            this.edIsLinked
        ) {
            // one garment line per item description; linked lines never merge
            return false;
        }
        return super.canBeMergedWith(...arguments);
    },

    setQuantity() {
        if (this.edIsLinked && !internalChange) {
            return {
                title: _t("Linked line"),
                body: _t("Change the garment line: its surcharges and express follow."),
            };
        }
        const result = super.setQuantity(...arguments);
        if (result === true && this.edIsGarment) {
            edInternal(() => {
                for (const child of this.edChildLines) {
                    child.setQuantity(this.qty, true);
                }
            });
        }
        return result;
    },

    setUnitPrice() {
        if (this.edIsLinked && !internalChange && this.order_id?.lines.includes(this)) {
            // surcharge and express prices follow their garment line
            return;
        }
        const res = super.setUnitPrice(...arguments);
        if (this.edIsGarment && this.edChildLines.length) {
            this.order_id.edRepriceLinked(this);
        }
        return res;
    },

    setDiscount() {
        super.setDiscount(...arguments);
        if (this.edIsGarment) {
            // a discount on a garment applies to its surcharges and express too
            edInternal(() => {
                for (const child of this.edChildLines) {
                    child.discount = this.discount;
                    child.earlydryer_discount_approver_employee_id =
                        this.earlydryer_discount_approver_employee_id;
                    child.earlydryer_discount_rule_id = this.earlydryer_discount_rule_id;
                }
            });
        }
    },
});

patch(PosOrder.prototype, {
    get edGarmentLines() {
        return this.lines.filter((line) => line.edIsGarment);
    },
    get edIsLaundry() {
        return this.edGarmentLines.length > 0;
    },
    get edTotalPieces() {
        return this.edGarmentLines.reduce((total, line) => total + line.edPieceCount, 0);
    },

    removeOrderline(line) {
        if (line.edIsLinked && !internalChange && line.edParentLine) {
            // removed with its garment line, or from the garment details
            return false;
        }
        const children = line.edIsGarment ? line.edChildLines : [];
        const res = super.removeOrderline(...arguments);
        if (res && children.length) {
            children.forEach((child) => this.edRemoveLinkedLine(child));
        }
        return res;
    },

    setPricelist() {
        super.setPricelist(...arguments);
        for (const line of this.edGarmentLines || []) {
            this.edRepriceLinked(line);
        }
    },

    // ------------------------------------------------------------------
    // Linked lines (same formulas as earlydryer.catalog.price_item)
    // ------------------------------------------------------------------

    _edRound(amount) {
        return this.currency ? this.currency.round(amount) : Math.round(amount * 100) / 100;
    },
    edLinkedPrice(garmentLine, child) {
        if (child.edKind === "express") {
            const service = garmentLine.edService;
            if (!service) {
                return 0;
            }
            return this._edRound(
                service.express_surcharge_kind === "fixed"
                    ? service.express_surcharge_value
                    : (garmentLine.price_unit * service.express_surcharge_value) / 100
            );
        }
        const surcharge = child.earlydryer_surcharge_id;
        if (surcharge?.compute_mode === "percent") {
            return this._edRound((garmentLine.price_unit * surcharge.percent) / 100);
        }
        // fixed surcharge: its own product in the order's price list
        return this._edRound(
            child.product_id.product_tmpl_id.getPrice(
                this.pricelist_id,
                1,
                0,
                false,
                child.product_id
            )
        );
    },
    /** Create a surcharge (or express) line attached to ``garmentLine``. */
    edAddLinkedLine(garmentLine, product, surcharge = false) {
        return edInternal(() => {
            const line = this.models["pos.order.line"].create({
                order_id: this,
                product_id: product,
                qty: garmentLine.qty,
                price_unit: 0,
                price_type: "manual",
                price_extra: 0,
                tax_ids: product.product_tmpl_id.taxes_id.map((tax) => ["link", tax]),
                discount: garmentLine.discount || 0,
                earlydryer_parent_line_uuid: garmentLine.uuid,
                earlydryer_surcharge_id: surcharge || false,
                earlydryer_discount_approver_employee_id:
                    garmentLine.earlydryer_discount_approver_employee_id || false,
                earlydryer_discount_rule_id: garmentLine.earlydryer_discount_rule_id || false,
            });
            line.setUnitPrice(this.edLinkedPrice(garmentLine, line));
            return line;
        });
    },
    edRemoveLinkedLine(line) {
        edInternal(() => this.removeOrderline(line));
    },
    /** Make the surcharge lines of ``garmentLine`` match ``surcharges``. */
    edSetSurcharges(garmentLine, surcharges) {
        const wanted = new Set(surcharges.map((s) => s.id));
        for (const child of garmentLine.edChildLines) {
            const id = child.earlydryer_surcharge_id?.id;
            if (id && !wanted.has(id)) {
                this.edRemoveLinkedLine(child);
            }
        }
        const have = new Set(garmentLine.edSurchargeIds);
        for (const surcharge of surcharges) {
            if (!have.has(surcharge.id) && surcharge.product_id) {
                this.edAddLinkedLine(garmentLine, surcharge.product_id, surcharge);
            }
        }
        this.selectOrderline(garmentLine);
    },
    /** Express lines follow the order's Express toggle, per garment service. */
    edApplyExpress(expressProduct) {
        for (const line of this.edGarmentLines) {
            const wanted = Boolean(this.earlydryer_express && line.edService?.express_available);
            const current = line.edChildLines.filter((child) => child.edKind === "express");
            if (wanted && !current.length && expressProduct) {
                this.edAddLinkedLine(line, expressProduct);
            } else if (!wanted) {
                current.forEach((child) => this.edRemoveLinkedLine(child));
            }
        }
    },

    edRepriceLinked(garmentLine) {
        edInternal(() => {
            for (const child of garmentLine.edChildLines) {
                child.price_type = "manual";
                child.setUnitPrice(this.edLinkedPrice(garmentLine, child));
            }
        });
    },

    /** Promise estimate: latest turnaround of the garments, in plant hours. */
    edPromiseEstimate(calendar, start = DateTime.now()) {
        const hours = this.edGarmentLines.map((line) => {
            const template = line.product_id.product_tmpl_id;
            const service = line.edService;
            if (this.earlydryer_express && service?.express_available) {
                return (
                    template.earlydryer_express_turnaround_hours || service.express_turnaround_hours
                );
            }
            return template.earlydryer_turnaround_hours || service?.standard_turnaround_hours || 0;
        });
        return hours.length ? estimatePromise(calendar, start, hours) : null;
    },
});
