import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { browser } from "@web/core/browser/browser";
import { PosStore } from "@point_of_sale/app/services/pos_store";
import { formatPrinted, normalizeCode } from "@earlydryer_pos/core/tag_code";
import { phoneDigits } from "@earlydryer_pos/core/phone";
import { EdDB } from "@earlydryer_pos/core/ed_db";

// background work of the counter while online (photos, collections, cache)
const LOOP_MS = 60 * 1000;
const REFRESH_MS = 2 * 60 * 1000;
const PHOTO_BACKOFF_MAX_MS = 30 * 60 * 1000;

patch(PosStore.prototype, {
    async afterProcessServerData() {
        await super.afterProcessServerData(...arguments);
        if (this.config.earlydryer_enabled) {
            await this.edInit();
        }
    },

    get edEnabled() {
        return Boolean(this.config.earlydryer_enabled && this.edState);
    },

    async edInit() {
        this.edDB = new EdDB(this.config.id);
        this.edState = {
            payload: this.config._earlydryer || {},
            collectedJobIds: [],
            collectionQueue: [],
            photosPending: 0,
            lastRefresh: 0,
        };
        try {
            const stored = await this.edDB.getValue("payload");
            if (stored && stored.generated_at > (this.edState.payload.generated_at || "")) {
                this.edState.payload = stored;
            }
            this.edState.collectedJobIds = await this.edDB.getValue("collected_job_ids", []);
            this.edState.collectionQueue = await this.edDB.getValue("collection_queue", []);
            await this.edCountPhotos();
        } catch (error) {
            console.warn("Earlydryer local store unavailable", error);
        }
        this.edSyncTagCounters();
        browser.addEventListener("pos-network-online", () => this.edBackground(true));
        browser.setInterval(() => this.edBackground(false), LOOP_MS);
        this.edBackground(true);
    },

    get edPayload() {
        return this.edState?.payload || {};
    },
    get edBranch() {
        return this.edPayload.branch || {};
    },
    get edOnline() {
        return !this.data.network.offline;
    },

    // ------------------------------------------------------------------
    // Catalogue
    // ------------------------------------------------------------------

    edKind(product) {
        return (product?.product_tmpl_id || product)?.earlydryer_kind || false;
    },
    edLaundryProducts() {
        return this.models["product.product"].filter(
            (product) =>
                this.edKind(product) === "laundry" && product.product_tmpl_id.available_in_pos
        );
    },
    edCategories() {
        const withProducts = new Set(
            this.edLaundryProducts().map(
                (product) => product.product_tmpl_id.earlydryer_garment_category_id?.id
            )
        );
        return this.models["earlydryer.garment.category"]
            .filter((category) => withProducts.has(category.id))
            .sort((a, b) => a.sequence - b.sequence || a.name.localeCompare(b.name));
    },
    edServicesFor(category) {
        return this.edLaundryProducts()
            .filter(
                (product) =>
                    product.product_tmpl_id.earlydryer_garment_category_id?.id === category.id
            )
            .map((product) => ({
                product,
                service: product.product_tmpl_id.earlydryer_service_type_id,
            }))
            .filter((entry) => entry.service)
            .sort((a, b) => a.service.sequence - b.service.sequence);
    },
    edSurchargesFor(product) {
        const template = product.product_tmpl_id;
        const category = template.earlydryer_garment_category_id;
        const service = template.earlydryer_service_type_id;
        return this.models["earlydryer.surcharge"]
            .filter(
                (surcharge) =>
                    (!surcharge.category_ids.length ||
                        surcharge.category_ids.some((c) => c.id === category?.id)) &&
                    (!surcharge.service_type_ids.length ||
                        surcharge.service_type_ids.some((s) => s.id === service?.id))
            )
            .sort((a, b) => a.sequence - b.sequence);
    },
    edProductById(id) {
        return id ? this.models["product.product"].get(id) : false;
    },
    get edExpressProduct() {
        return this.edProductById(this.edPayload.express_product_id);
    },
    get edSettlementProduct() {
        return this.edProductById(this.edPayload.settlement_product_id);
    },
    /** Unit price of ``product`` in the order's price list (offline engine). */
    edPrice(product, order = this.getOrder(), quantity = 1) {
        return product.product_tmpl_id.getPrice(order.pricelist_id, quantity, 0, false, product);
    },
    edIsWalkIn(partner) {
        return Boolean(partner && partner.id === this.config.earlydryer_walkin_partner_id?.id);
    },
    /** A real customer: name and phone, never the anonymous walk-in. */
    edHasRealCustomer(order = this.getOrder()) {
        if (order?.earlydryer_new_partner_name && order?.earlydryer_new_partner_phone) {
            return true;
        }
        const partner = order?.getPartner();
        return Boolean(partner && !this.edIsWalkIn(partner) && partner.name && partner.phone);
    },

    // ------------------------------------------------------------------
    // Tag numbers (printed mode)
    // ------------------------------------------------------------------

    _edCounterKey(range) {
        return `earlydryer_tag_next_${this.config.id}_${range.id}`;
    },
    /**
     * The next number of each range is the highest of: the server's, the one
     * stored in this browser, and one past the codes already on the orders
     * kept locally. A reload or a lost localStorage never reuses a number.
     */
    edSyncTagCounters() {
        const prefix = this.edBranch.tag_prefix || "";
        const used = [];
        for (const line of this.models["pos.order.line"].getAll()) {
            for (const code of (line.earlydryer_tag_codes || "").split(",")) {
                const value = normalizeCode(code);
                if (prefix && value.startsWith(prefix)) {
                    used.push(parseInt(value.slice(prefix.length, prefix.length + 7), 10));
                }
            }
        }
        for (const range of this.edPayload.ranges || []) {
            const key = this._edCounterKey(range);
            const stored = parseInt(browser.localStorage.getItem(key) || "0", 10);
            const inRange = used.filter((n) => n >= range.start_number && n <= range.end_number);
            const next = Math.max(range.next_number, stored, ...inRange.map((n) => n + 1));
            browser.localStorage.setItem(key, String(next));
        }
    },
    edTagNumbersLeft() {
        return (this.edPayload.ranges || []).reduce((left, range) => {
            const next = parseInt(
                browser.localStorage.getItem(this._edCounterKey(range)) || range.next_number,
                10
            );
            return left + Math.max(range.end_number - next + 1, 0);
        }, 0);
    },
    /**
     * Take ``count`` codes from the till's ranges, or null when there are
     * not enough numbers (the garments are then tagged at the counter).
     */
    edTakeTagCodes(count) {
        if (count <= 0) {
            return [];
        }
        if (this.edTagNumbersLeft() < count) {
            return null;
        }
        const branch = this.edBranch;
        const codes = [];
        for (const range of this.edPayload.ranges || []) {
            const key = this._edCounterKey(range);
            let next = parseInt(browser.localStorage.getItem(key) || range.next_number, 10);
            while (codes.length < count && next <= range.end_number) {
                codes.push(formatPrinted(branch.tag_prefix, next, branch.tag_check_digit));
                next += 1;
            }
            // stored before anything is printed
            browser.localStorage.setItem(key, String(next));
            if (codes.length === count) {
                break;
            }
        }
        return codes;
    },

    // ------------------------------------------------------------------
    // Collection cache
    // ------------------------------------------------------------------

    edCachedJobs() {
        const collected = new Set(this.edState?.collectedJobIds || []);
        return (this.edPayload.collection?.jobs || []).filter((job) => !collected.has(job.id));
    },
    edLookupOffline(code) {
        const value = (code || "").trim();
        if (!value) {
            return [];
        }
        const upper = normalizeCode(value);
        const digits = phoneDigits(value);
        const lower = value.toLowerCase();
        return this.edCachedJobs().filter(
            (job) =>
                job.pos_reference === value ||
                job.name.toUpperCase() === upper ||
                job.tags.includes(upper) ||
                (digits.length >= 6 && phoneDigits(job.partner_phone).endsWith(digits.slice(-9))) ||
                (lower.length >= 3 && job.partner_name.toLowerCase().includes(lower))
        );
    },
    async edMarkCollected(jobId) {
        this.edState.collectedJobIds = [...new Set([...this.edState.collectedJobIds, jobId])];
        await this.edDB.setValue("collected_job_ids", this.edState.collectedJobIds);
    },

    // ------------------------------------------------------------------
    // Queued collections
    // ------------------------------------------------------------------

    async edQueueCollection(collection) {
        this.edState.collectionQueue = [...this.edState.collectionQueue, collection];
        await this.edDB.setValue("collection_queue", this.edState.collectionQueue);
        await this.edMarkCollected(collection.job_id);
        this.edFlushCollections();
    },
    async edFlushCollections() {
        const queue = this.edState?.collectionQueue || [];
        if (!queue.length || !this.edOnline || this._edFlushingCollections) {
            return;
        }
        this._edFlushingCollections = true;
        try {
            // settlement orders first, so the server sees them paid
            await this.syncAllOrders();
            const results = await this.data.call(
                "earlydryer.pos.collection",
                "earlydryer_pos_submit",
                [this.config.id, queue]
            );
            const done = new Set(results.filter((r) => r.status !== "pending").map((r) => r.uuid));
            for (const result of results.filter((r) => r.status === "released_unpaid")) {
                this.notification.add(result.message, {
                    type: "warning",
                    title: _t("Released unpaid: the branch manager is told"),
                });
            }
            this.edState.collectionQueue = this.edState.collectionQueue.filter(
                (c) => !done.has(c.uuid)
            );
            await this.edDB.setValue("collection_queue", this.edState.collectionQueue);
        } catch (error) {
            console.warn("Earlydryer: collections not sent yet", error);
        } finally {
            this._edFlushingCollections = false;
        }
    },

    // ------------------------------------------------------------------
    // Photos
    // ------------------------------------------------------------------

    async edCountPhotos() {
        const photos = await this.edDB.getAll("photos");
        this.edState.photosPending = photos.length;
        return photos;
    },
    /** Keep a photo of ``line`` locally; it uploads once the order synced. */
    async edAddPhoto(order, line, data) {
        const index = line.earlydryer_photo_count || 0;
        await this.edDB.put("photos", {
            key: `${order.uuid}/${line.uuid}/${index}`,
            order_uuid: order.uuid,
            line_uuid: line.uuid,
            index,
            data,
            attempts: 0,
            next_try: 0,
        });
        line.earlydryer_photo_count = index + 1;
        await this.edCountPhotos();
        return index;
    },
    async edFlushPhotos() {
        if (!this.edOnline || this._edFlushingPhotos) {
            return;
        }
        this._edFlushingPhotos = true;
        try {
            const now = Date.now();
            for (const photo of await this.edCountPhotos()) {
                const order = this.models["pos.order"].getBy("uuid", photo.order_uuid);
                // only once the order is on the server
                if ((order && !order.isSynced) || photo.next_try > now) {
                    continue;
                }
                try {
                    const result = await this.data.call("pos.order", "earlydryer_upload_photo", [
                        photo.order_uuid,
                        photo.line_uuid,
                        photo.index,
                        photo.data,
                    ]);
                    if (result.status === "done") {
                        // deleted only once the server confirmed
                        await this.edDB.delete("photos", photo.key);
                        continue;
                    }
                } catch (error) {
                    console.warn("Earlydryer: photo upload failed", error);
                }
                const attempts = photo.attempts + 1;
                await this.edDB.put("photos", {
                    ...photo,
                    attempts,
                    next_try: now + Math.min(2 ** attempts * 30000, PHOTO_BACKOFF_MAX_MS),
                });
            }
        } finally {
            await this.edCountPhotos();
            this._edFlushingPhotos = false;
        }
    },

    // ------------------------------------------------------------------
    // Refresh while online
    // ------------------------------------------------------------------

    async edRefresh(force = false) {
        if (!this.edOnline || (!force && Date.now() - this.edState.lastRefresh < REFRESH_MS)) {
            return;
        }
        try {
            const payload = await this.data.call("pos.config", "earlydryer_pos_refresh", [
                this.config.id,
            ]);
            this.edState.lastRefresh = Date.now();
            this.edState.payload = payload;
            // the fresh cache knows the jobs collected here once sent
            const queued = new Set(this.edState.collectionQueue.map((c) => c.job_id));
            this.edState.collectedJobIds = this.edState.collectedJobIds.filter((id) =>
                queued.has(id)
            );
            await this.edDB.setValue("payload", payload);
            await this.edDB.setValue("collected_job_ids", this.edState.collectedJobIds);
            this.edSyncTagCounters();
        } catch (error) {
            console.warn("Earlydryer: refresh failed", error);
        }
    },
    async edBackground(force) {
        if (!this.edEnabled || !this.edOnline) {
            return;
        }
        await this.edFlushCollections();
        await this.edFlushPhotos();
        await this.edRefresh(force);
    },

    async postSyncAllOrders(orders) {
        await super.postSyncAllOrders(...arguments);
        if (this.edEnabled && orders?.length) {
            // photos of the orders just synced, then a fresh cache (throttled:
            // the cache of a busy plant is a few thousand jobs)
            this.edFlushPhotos();
            this.edRefresh(false);
        }
    },
});
