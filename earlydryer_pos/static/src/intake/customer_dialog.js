import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { usePos } from "@point_of_sale/app/hooks/pos_hook";
import { normalizeNigerianPhone, phoneDigits } from "@earlydryer_pos/core/phone";

/**
 * Customer first: search by phone or name (local, then server when online)
 * or quick-create with a name and a Nigerian phone. Offline, a new customer
 * is kept on the order and created (or matched by phone) when it syncs.
 * Payload: {partner} or {newName, newPhone}.
 */
export class EdCustomerDialog extends Component {
    static template = "earlydryer_pos.EdCustomerDialog";
    static components = { Dialog };
    static props = { getPayload: Function, close: Function };

    setup() {
        this.pos = usePos();
        this.state = useState({
            query: "",
            remote: [],
            searching: false,
            creating: false,
            name: "",
            phone: "",
            error: "",
        });
    }

    get results() {
        const query = this.state.query.trim().toLowerCase();
        if (query.length < 2) {
            return [];
        }
        const digits = phoneDigits(query);
        const walkIn = this.pos.config.earlydryer_walkin_partner_id?.id;
        const found = new Map();
        for (const partner of [...this.pos.models["res.partner"].getAll(), ...this.state.remote]) {
            if (!partner || partner.id === walkIn || found.has(partner.id)) {
                continue;
            }
            const byName = (partner.name || "").toLowerCase().includes(query);
            const byPhone =
                digits.length >= 4 && phoneDigits(partner.phone || "").includes(digits.slice(-9));
            if (byName || byPhone) {
                found.set(partner.id, partner);
            }
        }
        return [...found.values()].slice(0, 30);
    }

    async searchServer() {
        const query = this.state.query.trim();
        if (!query || !this.pos.edOnline) {
            return;
        }
        this.state.searching = true;
        try {
            const digits = phoneDigits(query);
            const domain =
                digits.length >= 4
                    ? ["|", ["name", "ilike", query], ["phone", "ilike", digits.slice(-9)]]
                    : [["name", "ilike", query]];
            this.state.remote = await this.pos.data.searchRead(
                "res.partner",
                domain,
                this.pos.data.fields["res.partner"],
                { limit: 20 }
            );
        } catch {
            this.state.remote = [];
        } finally {
            this.state.searching = false;
        }
    }

    startCreate() {
        const query = this.state.query.trim();
        this.state.creating = true;
        if (normalizeNigerianPhone(query)) {
            this.state.phone = query;
        } else {
            this.state.name = query;
        }
    }

    select(partner) {
        this.props.getPayload({ partner });
        this.props.close();
    }

    async create() {
        const name = this.state.name.trim();
        const phone = normalizeNigerianPhone(this.state.phone);
        if (!name) {
            this.state.error = _t("Enter the customer's name.");
            return;
        }
        if (!phone) {
            this.state.error = _t("Enter a valid phone number, e.g. 0803 123 4567.");
            return;
        }
        const existing = this.pos.models["res.partner"].find(
            (partner) => phoneDigits(partner.phone || "") === phoneDigits(phone)
        );
        if (existing) {
            this.state.error = _t("%s already has this phone number.", existing.name);
            return;
        }
        if (this.pos.edOnline) {
            try {
                const [partner] = await this.pos.data.create(
                    "res.partner",
                    [{ name, phone }],
                    false
                );
                if (partner) {
                    return this.select(partner);
                }
            } catch {
                // offline after all: keep it on the order
            }
        }
        this.props.getPayload({ newName: name, newPhone: phone });
        this.props.close();
    }
}
