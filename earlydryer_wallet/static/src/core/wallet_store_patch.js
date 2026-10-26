import { patch } from "@web/core/utils/patch";
import { browser } from "@web/core/browser/browser";
import { PosStore } from "@point_of_sale/app/services/pos_store";

// a refresh never holds the payment screen longer than this
const REFRESH_TIMEOUT_MS = 4000;

/**
 * Wallet balances on the till.
 *
 * The session loads the non-zero balances (``config._earlydryer_wallet``);
 * ``earlydryer.wallet.get_balance`` refreshes one customer when online. Wallet
 * payments validated on this till are kept in localStorage until the server
 * confirms it counts their order, so the cap stays right offline and after a
 * reload: available = known balance - local wallet payments not yet synced.
 */
patch(PosStore.prototype, {
    async afterProcessServerData() {
        await super.afterProcessServerData(...arguments);
        if (this.config.earlydryer_enabled) {
            this.edWalletInit();
        }
    },

    edWalletInit() {
        const payload = this.config._earlydryer_wallet || {};
        this.edWallet = {
            balances: { ...(payload.balances || {}) },
            methodIds: payload.method_ids || [],
            topupProductId: payload.topup_product_id || false,
        };
        if (this.edOnline) {
            const partnerIds = new Set(this.edWalletSpends().map((spend) => spend.partner_id));
            for (const partnerId of partnerIds) {
                this.edWalletRefresh(partnerId);
            }
        }
    },

    get edWalletEnabled() {
        return Boolean(this.edWallet);
    },

    edIsWalletMethod(method) {
        return Boolean(method?.earlydryer_is_wallet);
    },

    edIsTopupLine(line) {
        return this.edKind(line.getProduct?.() || line.product_id) === "wallet_topup";
    },

    // ------------------------------------------------------------------
    // Local spends (localStorage, like the tag counters)
    // ------------------------------------------------------------------

    _edWalletKey() {
        return `earlydryer_wallet_spends_${this.config.id}`;
    },

    edWalletSpends() {
        try {
            return JSON.parse(browser.localStorage.getItem(this._edWalletKey()) || "[]");
        } catch {
            return [];
        }
    },

    _edWalletSaveSpends(spends) {
        browser.localStorage.setItem(this._edWalletKey(), JSON.stringify(spends));
    },

    /** Record the wallet payments of a validated order, before printing. */
    edWalletRecord(order) {
        const partner = order.getPartner();
        const amount = order.payment_ids
            .filter((payment) => this.edIsWalletMethod(payment.payment_method_id))
            .reduce((total, payment) => total + payment.amount, 0);
        if (!partner || !amount) {
            return;
        }
        const spends = this.edWalletSpends().filter((spend) => spend.uuid !== order.uuid);
        spends.push({ uuid: order.uuid, partner_id: partner.id, amount, at: Date.now() });
        this._edWalletSaveSpends(spends);
    },

    // ------------------------------------------------------------------
    // Balances
    // ------------------------------------------------------------------

    edWalletKnown(partnerId) {
        return this.edWallet?.balances[String(partnerId)] || { balance: 0, blocked: false };
    },

    /** What the customer may still spend from the wallet on this till. */
    edWalletAvailable(partner) {
        if (!partner?.id || !this.edWallet) {
            return 0;
        }
        const known = this.edWalletKnown(partner.id);
        if (known.blocked) {
            return 0;
        }
        const pending = this.edWalletSpends()
            .filter((spend) => spend.partner_id === partner.id)
            .reduce((total, spend) => total + spend.amount, 0);
        return Math.max(this.config.currency_id.round(known.balance - pending), 0);
    },

    /** Ask the server for one customer's balance (online only, never blocks). */
    async edWalletRefresh(partnerId) {
        if (!this.edWallet || !partnerId || !this.edOnline) {
            return false;
        }
        const uuids = this.edWalletSpends()
            .filter((spend) => spend.partner_id === partnerId)
            .map((spend) => spend.uuid);
        try {
            const result = await Promise.race([
                this.data.call("earlydryer.wallet", "get_balance", [partnerId, uuids]),
                new Promise((resolve) => setTimeout(() => resolve(false), REFRESH_TIMEOUT_MS)),
            ]);
            if (!result) {
                return false;
            }
            this.edWallet.balances[String(partnerId)] = {
                balance: result.balance,
                blocked: result.blocked,
            };
            const synced = new Set(result.synced_uuids || []);
            if (synced.size) {
                this._edWalletSaveSpends(
                    this.edWalletSpends().filter((spend) => !synced.has(spend.uuid))
                );
            }
            return true;
        } catch (error) {
            console.warn("Wallet balance refresh failed", error);
            return false;
        }
    },

    setPartnerToCurrentOrder(partner) {
        const res = super.setPartnerToCurrentOrder(...arguments);
        if (partner?.id && this.edWalletEnabled) {
            this.edWalletRefresh(partner.id);
        }
        return res;
    },
});
