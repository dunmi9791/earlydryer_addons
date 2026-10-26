import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { formatCurrency } from "@web/core/currency";
import { compressPhoto } from "@earlydryer_pos/photos/photo_capture";
import { isValidPreprinted, normalizeCode } from "@earlydryer_pos/core/tag_code";

export const COLOURS = [
    ["White", "#ffffff"],
    ["Black", "#000000"],
    ["Navy", "#1f2a52"],
    ["Blue", "#2f6fd6"],
    ["Grey", "#8a8f98"],
    ["Brown", "#7a4b2a"],
    ["Beige", "#e3d3b5"],
    ["Red", "#c62828"],
    ["Green", "#2e7d32"],
    ["Yellow", "#f2c94c"],
    ["Pink", "#f48fb1"],
    ["Purple", "#7b3fa0"],
    ["Gold", "#c9a227"],
    ["Multi", "linear-gradient(90deg,#c62828,#f2c94c,#2e7d32,#2f6fd6)"],
];
export const CONDITIONS = [
    _t("stain"),
    _t("tear"),
    _t("missing button"),
    _t("faded"),
    _t("hole"),
    _t("loose seam"),
];

/**
 * Garment details: surcharges, colour, brand, condition, photos and, in
 * pre-printed mode, the tag of each piece. Applies to every unit of the line.
 */
export class EdLineDetailsDialog extends Component {
    static template = "earlydryer_pos.EdLineDetailsDialog";
    static components = { Dialog };
    static props = { line: Object, getPayload: Function, close: Function };

    setup() {
        this.pos = usePos();
        const line = this.props.line;
        this.colours = COLOURS;
        this.conditions = CONDITIONS;
        this.state = useState({
            surchargeIds: new Set(line.edSurchargeIds),
            colour: line.earlydryer_colour || "",
            brand: line.earlydryer_brand || "",
            condition: line.earlydryer_condition_note || "",
            codes: this.preprinted
                ? Array.from({ length: line.edPieceCount }, (_, i) => line.edTagCodes[i] || "")
                : [],
            photoCount: line.earlydryer_photo_count || 0,
            busy: false,
            error: "",
        });
    }

    get line() {
        return this.props.line;
    }
    get preprinted() {
        return this.pos.edBranch.tag_mode === "preprinted" && this.props.line.edNeedsTags;
    }
    get surcharges() {
        return this.pos.edSurchargesFor(this.line.product_id);
    }
    surchargeLabel(surcharge) {
        if (surcharge.compute_mode === "percent") {
            return `+${surcharge.percent}%`;
        }
        const price = this.line.order_id.edLinkedPrice(this.line, {
            edKind: "surcharge",
            earlydryer_surcharge_id: surcharge,
            product_id: surcharge.product_id,
        });
        return "+" + formatCurrency(price, this.pos.config.currency_id.id);
    }
    toggleSurcharge(surcharge) {
        const ids = new Set(this.state.surchargeIds);
        if (ids.has(surcharge.id)) {
            ids.delete(surcharge.id);
        } else {
            ids.add(surcharge.id);
        }
        this.state.surchargeIds = ids;
    }
    addCondition(word) {
        const current = this.state.condition.trim();
        const parts = current ? current.split(/,\s*/) : [];
        if (!parts.includes(word)) {
            parts.push(word);
        }
        this.state.condition = parts.join(", ");
    }
    onCodeKeydown(ev, index) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            const next = ev.target.closest(".ed-codes")?.querySelectorAll("input")[index + 1];
            next?.focus();
        }
    }

    async onPhoto(ev) {
        const files = [...(ev.target.files || [])];
        ev.target.value = "";
        if (!files.length) {
            return;
        }
        this.state.busy = true;
        try {
            for (const file of files) {
                const data = await compressPhoto(file);
                await this.pos.edAddPhoto(this.line.order_id, this.line, data);
            }
            this.state.photoCount = this.line.earlydryer_photo_count;
        } catch (error) {
            this.state.error = _t("The photo could not be read: %s", error?.message || error);
        } finally {
            this.state.busy = false;
        }
    }

    validateCodes() {
        const codes = this.state.codes.map(normalizeCode);
        const pattern = this.pos.edBranch.tag_preprinted_pattern;
        const used = new Set();
        for (const other of this.line.order_id.edGarmentLines) {
            if (other !== this.line) {
                other.edTagCodes.forEach((code) => used.add(code));
            }
        }
        for (const code of codes.filter(Boolean)) {
            if (!isValidPreprinted(code, pattern)) {
                return _t("%s is not a tag of this plant.", code);
            }
            if (used.has(code)) {
                return _t("Tag %s is used twice on this order.", code);
            }
            used.add(code);
        }
        return "";
    }

    apply() {
        if (this.preprinted) {
            const error = this.validateCodes();
            if (error) {
                this.state.error = error;
                return;
            }
            this.line.earlydryer_tag_codes = this.state.codes.map(normalizeCode).join(",");
        }
        this.line.earlydryer_colour = this.state.colour.trim() || false;
        this.line.earlydryer_brand = this.state.brand.trim() || false;
        this.line.earlydryer_condition_note = this.state.condition.trim() || false;
        const surcharges = this.surcharges.filter((s) => this.state.surchargeIds.has(s.id));
        this.line.order_id.edSetSurcharges(this.line, surcharges);
        this.props.getPayload(true);
        this.props.close();
    }
}
