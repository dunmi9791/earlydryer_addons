import { Component, onMounted, onWillStart, onWillUnmount, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { ConnectionLostError, RPCError } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { RiderStore, newUuid } from "./rider_queue";
import { SignaturePad } from "./signature_pad";

const API = "earlydryer.logistics.rider.api";
const RETRY_MS = 20 * 1000;
const PHOTO_MAX_SIDE = 1280;
const PHOTO_QUALITY = 0.7;
const GPS_TIMEOUT_MS = 15 * 1000;
const CLOSED = ["done", "failed", "cancelled"];

/** Resize and compress a camera picture (same settings as the POS photos). */
async function compressPhoto(file) {
    const url = URL.createObjectURL(file);
    try {
        const img = await new Promise((resolve, reject) => {
            const image = new Image();
            image.onload = () => resolve(image);
            image.onerror = reject;
            image.src = url;
        });
        const scale = Math.min(1, PHOTO_MAX_SIDE / Math.max(img.naturalWidth, img.naturalHeight));
        const canvas = document.createElement("canvas");
        canvas.width = Math.round(img.naturalWidth * scale);
        canvas.height = Math.round(img.naturalHeight * scale);
        canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
        return canvas.toDataURL("image/jpeg", PHOTO_QUALITY).split(",")[1];
    } finally {
        URL.revokeObjectURL(url);
    }
}

/** Current position, or null (denied, unavailable, timeout). */
function readPosition() {
    if (!navigator.geolocation) {
        return Promise.resolve(null);
    }
    return new Promise((resolve) => {
        navigator.geolocation.getCurrentPosition(
            (pos) =>
                resolve({
                    lat: pos.coords.latitude,
                    lng: pos.coords.longitude,
                    accuracy: Math.round(pos.coords.accuracy || 0),
                    at: new Date().toISOString().replace("T", " ").slice(0, 19),
                }),
            () => resolve(null),
            { enableHighAccuracy: true, timeout: GPS_TIMEOUT_MS, maximumAge: 30 * 1000 }
        );
    });
}

function nowString() {
    return new Date().toISOString().replace("T", " ").slice(0, 19);
}

/**
 * "My Trips": the rider's phone screen.
 *
 * Every action is written to IndexedDB first, applied to the screen at once
 * and sent when the network allows (idempotent per action UUID on the
 * server). Photos upload after their stop synced. The trip data stays in the
 * open screen and in IndexedDB, so stops can be finished without network;
 * the Odoo web client itself cannot be reloaded offline.
 */
export class RiderView extends Component {
    static template = "earlydryer_logistics.RiderView";
    static components = { SignaturePad };
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.store = new RiderStore(user.userId);
        this.state = useState({
            loading: true,
            online: navigator.onLine,
            data: { trips: [], fail_reasons: [], approvers: [], gps_threshold: 100 },
            tripId: false,
            stopId: false,
            mode: false, // complete | fail
            form: {},
            pending: 0,
            photosPending: 0,
            errors: [],
            scanMessage: "",
            syncing: false,
            lastSync: false,
        });
        this.onOnline = () => {
            this.state.online = true;
            this.sync();
        };
        this.onOffline = () => (this.state.online = false);
        onWillStart(() => this.load());
        onMounted(() => {
            window.addEventListener("online", this.onOnline);
            window.addEventListener("offline", this.onOffline);
            this.timer = setInterval(() => this.sync(), RETRY_MS);
        });
        onWillUnmount(() => {
            window.removeEventListener("online", this.onOnline);
            window.removeEventListener("offline", this.onOffline);
            clearInterval(this.timer);
        });
    }

    // ------------------------------------------------------------------
    // Data
    // ------------------------------------------------------------------

    async load() {
        try {
            const cached = await this.store.getValue("data");
            if (cached) {
                this.state.data = cached;
            }
        } catch (error) {
            console.warn("Rider store unavailable", error);
        }
        await this.refreshCounters();
        await this.sync();
        this.state.loading = false;
    }

    async refresh() {
        try {
            const data = await this.orm.call(API, "rider_data", []);
            // keep local changes still waiting to be sent
            const actions = await this.store.all("actions");
            for (const action of actions) {
                this.applyLocal(action, data);
            }
            this.state.data = data;
            this.state.online = true;
            this.state.lastSync = nowString();
            await this.store.setValue("data", data);
        } catch (error) {
            if (!this.isNetworkError(error)) {
                throw error;
            }
            this.state.online = false;
        }
    }

    async refreshCounters() {
        try {
            this.state.pending = (await this.store.all("actions")).length;
            this.state.photosPending = (await this.store.all("photos")).length;
        } catch {
            this.state.pending = 0;
        }
    }

    isNetworkError(error) {
        return error instanceof ConnectionLostError || error?.name === "ConnectionLostError";
    }

    get trips() {
        return this.state.data.trips || [];
    }

    get trip() {
        return this.trips.find((t) => t.id === this.state.tripId);
    }

    get stop() {
        return this.trip?.stops.find((s) => s.id === this.state.stopId);
    }

    findStop(data, stopId) {
        for (const trip of data.trips || []) {
            const stop = trip.stops.find((s) => s.id === stopId);
            if (stop) {
                return [trip, stop];
            }
        }
        return [null, null];
    }

    reasonsFor(stop) {
        return (this.state.data.fail_reasons || []).filter(
            (r) => r.stop_type === "both" || r.stop_type === stop.type
        );
    }

    formatAmount(amount, symbol) {
        const value = Number(amount || 0).toLocaleString(undefined, {
            minimumFractionDigits: 0,
            maximumFractionDigits: 2,
        });
        return `${symbol || ""}${value}`;
    }

    isClosed(stop) {
        return CLOSED.includes(stop.state);
    }

    // ------------------------------------------------------------------
    // Queue
    // ------------------------------------------------------------------

    /** Optimistic effect of a queued action on the trip data. */
    applyLocal(action, data = this.state.data) {
        const args = action.args;
        if (action.method === "rider_start_trip") {
            const trip = (data.trips || []).find((t) => t.id === args[1]);
            if (trip) {
                trip.state = "in_progress";
                for (const stop of trip.stops) {
                    if (stop.type === "pickup" && stop.state === "assigned") {
                        stop.state = "en_route";
                    }
                }
            }
            return;
        }
        if (action.method === "rider_scan") {
            return; // the server decides (release check)
        }
        const [, stop] = this.findStop(data, args[1]);
        if (!stop) {
            return;
        }
        stop.pending = true;
        if (action.method === "rider_arrive") {
            stop.state = "arrived";
        } else if (action.method === "rider_complete") {
            stop.state = "done";
            stop.cash_collected = args[2].cash_collected || 0;
            stop.collection_method = args[2].collection_method || false;
        } else if (action.method === "rider_fail") {
            stop.state = "failed";
        }
    }

    async enqueue(method, args) {
        const uuid = newUuid();
        const action = { key: uuid, uuid, method, args: [uuid, ...args], created: Date.now() };
        this.applyLocal(action);
        try {
            await this.store.put("actions", action);
            await this.store.setValue("data", this.state.data);
        } catch (error) {
            // no IndexedDB (private mode...): send at once, keep in memory
            this.memoryQueue = [...(this.memoryQueue || []), action];
        }
        await this.refreshCounters();
        this.sync();
        return uuid;
    }

    async sync() {
        if (this.state.syncing) {
            return;
        }
        this.state.syncing = true;
        try {
            let actions = [];
            try {
                actions = await this.store.all("actions");
            } catch {
                actions = this.memoryQueue || [];
            }
            for (const action of actions) {
                try {
                    const result = await this.orm.call(API, action.method, action.args);
                    if (action.method === "rider_scan" && result) {
                        this.state.scanMessage = result.message;
                        if (!["ok", "duplicate"].includes(result.result)) {
                            this.notification.add(result.message, { type: "warning" });
                        }
                    }
                } catch (error) {
                    if (this.isNetworkError(error)) {
                        this.state.online = false;
                        return;
                    }
                    // refused by the server: show it, drop the action
                    const message =
                        error instanceof RPCError ? error.data?.message || error.message : String(error);
                    this.state.errors.push({ key: action.key, message });
                    this.notification.add(message, { type: "danger", sticky: true });
                }
                await this.store.delete("actions", action.key).catch(() => {});
                this.memoryQueue = (this.memoryQueue || []).filter((a) => a.key !== action.key);
            }
            await this.uploadPhotos();
            await this.refresh();
        } finally {
            this.state.syncing = false;
            await this.refreshCounters();
        }
    }

    async uploadPhotos() {
        let photos = [];
        try {
            photos = await this.store.all("photos");
        } catch {
            return;
        }
        const actions = await this.store.all("actions").catch(() => []);
        for (const photo of photos) {
            // the stop must be on the server first
            if (actions.some((a) => a.args[1] === photo.stopId && a.method !== "rider_scan")) {
                continue;
            }
            try {
                await this.orm.call(API, "rider_upload_photo", [
                    photo.uuid,
                    photo.stopId,
                    photo.data,
                    "image/jpeg",
                ]);
            } catch (error) {
                if (this.isNetworkError(error)) {
                    this.state.online = false;
                    return;
                }
                this.notification.add(error.data?.message || String(error), { type: "danger" });
            }
            await this.store.delete("photos", photo.key).catch(() => {});
        }
    }

    // ------------------------------------------------------------------
    // Trips
    // ------------------------------------------------------------------

    openTrip(trip) {
        this.state.tripId = trip.id;
        this.state.stopId = false;
        this.state.mode = false;
        this.state.scanMessage = "";
    }

    back() {
        if (this.state.mode) {
            this.state.mode = false;
        } else if (this.state.stopId) {
            this.state.stopId = false;
        } else {
            this.state.tripId = false;
        }
    }

    async startTrip(trip) {
        let odometer = null;
        if (trip.has_vehicle) {
            const value = window.prompt(_t("Odometer reading (km)"), trip.odometer_start || "");
            if (value === null) {
                return;
            }
            odometer = value ? Number(value) : null;
        }
        await this.enqueue("rider_start_trip", [trip.id, odometer]);
    }

    async onScan(ev) {
        if (ev.key !== "Enter") {
            return;
        }
        const code = ev.target.value.trim();
        ev.target.value = "";
        if (!code) {
            return;
        }
        this.state.scanMessage = this.state.online ? _t("Checking %s...", code) : _t("%s queued (offline)", code);
        await this.enqueue("rider_scan", [this.trip.id, code]);
    }

    // ------------------------------------------------------------------
    // Stops
    // ------------------------------------------------------------------

    openStop(stop) {
        this.state.stopId = stop.id;
        this.state.mode = false;
    }

    async arrive(stop) {
        const gps = await readPosition();
        if (!gps) {
            this.notification.add(_t("No GPS position: allow location for this site."), {
                type: "warning",
            });
        } else if (gps.accuracy > this.state.data.gps_threshold) {
            this.notification.add(_t("Low GPS accuracy (%s m): recorded anyway.", gps.accuracy), {
                type: "warning",
            });
        }
        await this.enqueue("rider_arrive", [stop.id, gps, nowString()]);
    }

    startComplete(stop) {
        this.state.form = {
            recipient_name: "",
            signature: false,
            cash_collected: stop.type === "delivery" ? stop.cod_amount : 0,
            collection_method: stop.type === "delivery" && stop.cod_amount ? "cash" : "none",
            approver_employee_id: "",
            pin: "",
            bag_count: stop.bag_count || 1,
            piece_count_estimate: 0,
            pickup_note: "",
            save_location: !stop.has_location,
            fix_location: false,
            photos: 0,
        };
        this.state.mode = "complete";
    }

    startFail(stop) {
        this.state.form = { reason_id: "", note: "" };
        this.state.mode = "fail";
    }

    onSignature(dataUrl) {
        this.state.form.signature = dataUrl;
    }

    async onPhoto(ev) {
        const stop = this.stop;
        for (const file of ev.target.files || []) {
            const data = await compressPhoto(file);
            const uuid = newUuid();
            await this.store
                .put("photos", { key: uuid, uuid, stopId: stop.id, data, created: Date.now() })
                .catch(() => this.notification.add(_t("Photo not stored on the phone."), { type: "danger" }));
            this.state.form.photos = (this.state.form.photos || 0) + 1;
        }
        ev.target.value = "";
        await this.refreshCounters();
    }

    get short() {
        const stop = this.stop;
        const form = this.state.form;
        if (!stop || stop.type !== "delivery") {
            return 0;
        }
        const paid = form.collection_method === "cash" ? Number(form.cash_collected || 0) : 0;
        if (form.collection_method === "transfer_confirmed") {
            return 0;
        }
        return Math.max(Math.round((stop.cod_amount - paid) * 100) / 100, 0);
    }

    async confirmComplete() {
        const stop = this.stop;
        const form = this.state.form;
        if (!form.signature) {
            this.notification.add(_t("Ask the customer to sign."), { type: "warning" });
            return;
        }
        if (stop.type === "pickup" && Number(form.bag_count) <= 0) {
            this.notification.add(_t("Count the bags."), { type: "warning" });
            return;
        }
        let offline = false;
        if (this.short > 0 && !stop.credit_approved) {
            if (!form.approver_employee_id || !form.pin) {
                this.notification.add(
                    _t("Short collection: a manager must enter their PIN, or fail the stop (Unable to pay)."),
                    { type: "warning", sticky: true }
                );
                return;
            }
            if (this.state.online) {
                try {
                    const check = await this.orm.call(API, "rider_check_pin", [
                        stop.id,
                        Number(form.approver_employee_id),
                        form.pin,
                    ]);
                    if (!check.ok) {
                        this.notification.add(_t("PIN refused."), { type: "danger" });
                        return;
                    }
                } catch (error) {
                    if (!this.isNetworkError(error)) {
                        throw error;
                    }
                    offline = true;
                }
            } else {
                offline = true;
            }
        }
        const gps = await readPosition();
        const vals = {
            recipient_name: form.recipient_name,
            signature: form.signature,
            gps,
            done_on: nowString(),
            save_location: form.save_location,
            fix_location: form.fix_location,
            offline,
        };
        if (stop.type === "delivery") {
            Object.assign(vals, {
                collection_method: form.collection_method,
                cash_collected:
                    form.collection_method === "cash" ? Number(form.cash_collected || 0) : 0,
                approver_employee_id: form.approver_employee_id
                    ? Number(form.approver_employee_id)
                    : false,
                pin: form.pin || false,
            });
        } else {
            Object.assign(vals, {
                bag_count: Number(form.bag_count),
                piece_count_estimate: Number(form.piece_count_estimate || 0),
                pickup_note: form.pickup_note,
            });
        }
        await this.enqueue("rider_complete", [stop.id, vals]);
        this.state.mode = false;
        this.state.stopId = false;
    }

    async confirmFail() {
        const stop = this.stop;
        const form = this.state.form;
        const reason = this.reasonsFor(stop).find((r) => r.id === Number(form.reason_id));
        if (!reason) {
            this.notification.add(_t("Choose a reason."), { type: "warning" });
            return;
        }
        if (reason.note_required && !form.note.trim()) {
            this.notification.add(_t("This reason needs a note."), { type: "warning" });
            return;
        }
        const gps = await readPosition();
        await this.enqueue("rider_fail", [stop.id, reason.id, form.note, gps, nowString()]);
        this.state.mode = false;
        this.state.stopId = false;
    }
}

registry.category("actions").add("earlydryer_logistics.rider_view", RiderView);
