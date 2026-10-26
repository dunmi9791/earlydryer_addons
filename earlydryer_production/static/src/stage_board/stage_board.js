import { Component, onMounted, onWillStart, onWillUnmount, useRef, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useBus, useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const { DateTime } = luxon;
const MODEL = "laundry.job";
const LATE_STATES = ["packed", "ready", "out_for_delivery"];
const CHANNEL_PREFIX = "earlydryer_board_";

function sortKey(card) {
    // overdue first, then express, then promised time (none last)
    return [!card.overdue, !card.express, card.promised_on || "9999", card.id];
}

function compareCards(a, b) {
    const ka = sortKey(a);
    const kb = sortKey(b);
    for (let i = 0; i < ka.length; i++) {
        if (ka[i] < kb[i]) {
            return -1;
        }
        if (ka[i] > kb[i]) {
            return 1;
        }
    }
    return 0;
}

function hoursLabel(minutes) {
    const abs = Math.abs(minutes);
    if (abs < 60) {
        return _t("%s min", Math.round(abs));
    }
    if (abs < 48 * 60) {
        return _t("%s h", Math.round(abs / 60));
    }
    return _t("%s d", Math.round(abs / 1440));
}

/**
 * Stage board: the plant's jobs by stage, moved by drag, "Move to…" or
 * scan. The board never changes a stage on its own: every move goes
 * through laundry.job.earlydryer_board_move (action_move_to) and the cards
 * come back from the server. Live updates arrive on the branch's bus
 * channel; without the bus the board polls.
 */
export class EarlydryerStageBoard extends Component {
    static template = "earlydryer_production.StageBoard";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.busService = useService("bus_service");
        this.scanRef = useRef("scanInput");
        this.state = useState({
            data: null,
            branchId: false,
            filters: { express: false, overdue: false, due_today: false, channel: "", search: "" },
            selected: [],
            highlightId: false,
            errors: {},
            picker: null,
            moveMenu: false,
            panel: null,
            scanOffer: null,
            tabletMode: false,
            identity: null,
            targetState: "sorted",
            pinPad: false,
            pin: "",
            message: null,
            now: DateTime.utc(),
            busy: false,
        });
        this.channel = false;
        const barcode = useService("barcode");
        useBus(barcode.bus, "barcode_scanned", (ev) => this.onScan(ev.detail.barcode));
        this.onBusNotification = (payload) => this.onBusUpdate(payload);
        this.busService.subscribe("earlydryer.board/updated", this.onBusNotification);
        this.busService.subscribe("earlydryer.board/machines", this.onBusNotification);
        onWillStart(() => this.load());
        onMounted(() => {
            this.focusScan();
            // relative times, idle tablet, polling when the bus is down
            this.ticker = setInterval(() => this.tick(), 5000);
        });
        onWillUnmount(() => {
            clearInterval(this.ticker);
            this.busService.unsubscribe("earlydryer.board/updated", this.onBusNotification);
            this.busService.unsubscribe("earlydryer.board/machines", this.onBusNotification);
            if (this.channel) {
                this.busService.deleteChannel(this.channel);
            }
            this.releaseIdentity();
        });
    }

    // ------------------------------------------------------------------
    // Loading
    // ------------------------------------------------------------------

    async load() {
        const data = await this.orm.call(MODEL, "earlydryer_board_data", [], {
            branch_id: this.state.branchId,
            filters: this.state.filters,
        });
        if (this.state.branchId !== data.branch.id && this.state.identity) {
            this.releaseIdentity();
        }
        this.state.data = data;
        this.state.branchId = data.branch.id;
        this.state.tabletMode = this.state.tabletMode
            ? data.branch.production_mode !== "front_desk"
            : data.branch.production_mode === "tablet";
        this.lastLoad = Date.now();
        this.subscribe(data.branch.id);
    }

    subscribe(branchId) {
        const channel = `${CHANNEL_PREFIX}${branchId}`;
        if (channel === this.channel) {
            return;
        }
        if (this.channel) {
            this.busService.deleteChannel(this.channel);
        }
        this.channel = channel;
        this.busService.addChannel(channel);
    }

    get filtersActive() {
        const f = this.state.filters;
        return f.express || f.overdue || f.due_today || f.channel || f.search;
    }

    onBusUpdate(payload) {
        if (!this.state.data || payload.branch_id !== this.state.branchId) {
            return;
        }
        if (this.filtersActive) {
            // the card endpoint ignores the filters: reload the filtered board
            return this.load();
        }
        return this.refreshCards(payload.job_ids || []);
    }

    async refreshCards(jobIds) {
        const res = await this.orm.call(MODEL, "earlydryer_board_cards", [jobIds], {
            branch_id: this.state.branchId,
        });
        this.applyCards(res);
    }

    applyCards(res) {
        const data = this.state.data;
        const gone = new Set([...(res.removed_ids || []), ...res.cards.map((c) => c.id)]);
        for (const column of data.columns) {
            column.cards = column.cards.filter((c) => !gone.has(c.id));
        }
        for (const card of res.cards) {
            const column = data.columns.find((c) => c.state === card.state);
            if (column) {
                column.cards.push(card);
                column.cards.sort(compareCards);
            }
        }
        if (res.final_counts) {
            data.final_counts = res.final_counts;
        }
        if (res.machines) {
            data.machines = res.machines;
        }
        const visible = new Set(data.columns.flatMap((c) => c.cards.map((card) => card.id)));
        this.state.selected = this.state.selected.filter((id) => visible.has(id));
    }

    tick() {
        this.state.now = DateTime.utc();
        const identity = this.state.identity;
        if (identity && Date.now() > identity.expiresAt) {
            this.releaseIdentity();
            this.state.message = { type: "info", text: _t("Tablet idle: identify again.") };
        }
        const data = this.state.data;
        const live = this.busService.workerState === "CONNECTED";
        if (data && !live && Date.now() - this.lastLoad > data.branch.refresh_seconds * 1000) {
            this.load();
        }
    }

    // ------------------------------------------------------------------
    // Display helpers
    // ------------------------------------------------------------------

    get rights() {
        return this.state.data.rights;
    }

    get targetStates() {
        const columns = this.state.data.columns.map((c) => [c.state, c.label]);
        return this.rights.late_stages
            ? columns
            : columns.filter(([state]) => !LATE_STATES.includes(state));
    }

    promisedLabel(card) {
        if (!card.promised_on) {
            return "";
        }
        const promised = DateTime.fromSQL(card.promised_on, { zone: "utc" });
        const minutes = promised.diff(this.state.now, "minutes").minutes;
        return minutes >= 0
            ? _t("in %s", hoursLabel(minutes))
            : _t("%s late", hoursLabel(minutes));
    }

    oldestLabel(column) {
        const dates = column.cards.map((c) => c.stage_since).filter(Boolean).sort();
        if (!dates.length) {
            return "";
        }
        const since = DateTime.fromSQL(dates[0], { zone: "utc" });
        return hoursLabel(this.state.now.diff(since, "minutes").minutes);
    }

    machineClass(machine) {
        return {
            available: "text-bg-success",
            in_use: "text-bg-warning",
            down: "text-bg-danger",
        }[machine.status];
    }

    isSelected(card) {
        return this.state.selected.includes(card.id);
    }

    get overlayOpen() {
        const s = this.state;
        return Boolean(s.picker || s.moveMenu || s.panel || s.pinPad);
    }

    focusScan() {
        if (this.overlayOpen) {
            return;
        }
        setTimeout(() => this.scanRef.el?.focus(), 0);
    }

    onScanBlur() {
        setTimeout(() => {
            const active = document.activeElement;
            if (!active || active === document.body) {
                this.focusScan();
            }
        }, 200);
    }

    // ------------------------------------------------------------------
    // Filters and branch
    // ------------------------------------------------------------------

    toggleFilter(name) {
        this.state.filters[name] = !this.state.filters[name];
        this.load();
    }

    onFilterChange() {
        this.load();
    }

    onSearchKeydown(ev) {
        if (ev.key === "Enter") {
            this.load();
        }
    }

    onBranchChange(ev) {
        this.state.branchId = parseInt(ev.target.value);
        this.state.selected = [];
        this.load();
    }

    toggleTabletMode() {
        this.state.tabletMode = !this.state.tabletMode;
        this.releaseIdentity();
        this.focusScan();
    }

    // ------------------------------------------------------------------
    // Selection, drag and drop
    // ------------------------------------------------------------------

    toggleSelect(card, ev) {
        ev.stopPropagation();
        const selected = this.state.selected;
        const index = selected.indexOf(card.id);
        if (index >= 0) {
            selected.splice(index, 1);
        } else {
            selected.push(card.id);
        }
    }

    onDragStart(card, ev) {
        if (!this.rights.move) {
            ev.preventDefault();
            return;
        }
        ev.dataTransfer.setData("text/plain", String(card.id));
        ev.dataTransfer.effectAllowed = "move";
        this.dragIds = this.isSelected(card) ? [...this.state.selected] : [card.id];
    }

    onDragOver(ev) {
        if (this.dragIds) {
            ev.preventDefault();
        }
    }

    onDrop(column, ev) {
        ev.preventDefault();
        const ids = this.dragIds || [];
        this.dragIds = null;
        const movable = ids.filter((id) => this.cardById(id)?.state !== column.state);
        if (movable.length) {
            this.requestMove(movable, column.state);
        }
    }

    cardById(id) {
        for (const column of this.state.data.columns) {
            const card = column.cards.find((c) => c.id === id);
            if (card) {
                return card;
            }
        }
        return null;
    }

    openMoveMenu() {
        this.state.moveMenu = true;
    }

    closeOverlays() {
        Object.assign(this.state, { picker: null, moveMenu: false, panel: null, pinPad: false, pin: "" });
        this.focusScan();
    }

    chooseTarget(target) {
        const ids = [...this.state.selected];
        this.state.moveMenu = false;
        this.requestMove(ids, target);
    }

    // ------------------------------------------------------------------
    // Moving
    // ------------------------------------------------------------------

    async requestMove(jobIds, target) {
        if (!this.rights.move || !jobIds.length) {
            return;
        }
        const data = this.state.data;
        if (
            target === "sorted" &&
            jobIds.length === 1 &&
            data.branch.require_sorting_colour_group &&
            this.cardById(jobIds[0])?.unsorted
        ) {
            return this.openSort(jobIds[0]);
        }
        if (data.employee_states.includes(target)) {
            if (this.state.tabletMode) {
                if (!this.state.identity) {
                    this.state.message = {
                        type: "warning",
                        text: _t("Scan your badge or type your PIN first."),
                    };
                    return this.focusScan();
                }
                return this.doMove(jobIds, target, false);
            }
            this.state.picker = { jobIds, target, label: this.stateLabel(target) };
            return;
        }
        return this.doMove(jobIds, target, false);
    }

    stateLabel(state) {
        const column = this.state.data.columns.find((c) => c.state === state);
        return column ? column.label : state;
    }

    pickEmployee(employee) {
        const { jobIds, target } = this.state.picker;
        this.state.picker = null;
        this.doMove(jobIds, target, employee.id);
    }

    async doMove(jobIds, target, employeeId) {
        this.state.busy = true;
        try {
            const res = await this.orm.call(MODEL, "earlydryer_board_move", [jobIds, target], {
                employee_id: employeeId || false,
                tablet_token: this.state.tabletMode ? this.state.identity?.token || false : false,
            });
            for (const result of res.results) {
                if (result.ok) {
                    delete this.state.errors[result.job_id];
                } else {
                    this.state.errors[result.job_id] = result.message;
                    setTimeout(() => delete this.state.errors[result.job_id], 10000);
                }
            }
            this.applyCards(res);
            this.touchIdentity();
            this.state.selected = this.state.selected.filter(
                (id) => !res.results.some((r) => r.ok && r.job_id === id)
            );
        } catch (error) {
            // e.g. the tablet identification timed out on the server
            this.state.identity = null;
            throw error;
        } finally {
            this.state.busy = false;
            this.state.scanOffer = null;
            this.focusScan();
        }
    }

    // ------------------------------------------------------------------
    // Scanning
    // ------------------------------------------------------------------

    onScanKeydown(ev) {
        if (ev.key !== "Enter") {
            return;
        }
        ev.preventDefault();
        const code = ev.target.value;
        ev.target.value = "";
        if (!code.trim() && this.state.scanOffer) {
            // Enter on an empty scan bar accepts the offered move
            const { jobId, next } = this.state.scanOffer;
            return this.requestMove([jobId], next);
        }
        this.onScan(code);
    }

    async onScan(rawCode) {
        const code = (rawCode || "").trim().toUpperCase();
        if (!code || this.overlayOpen) {
            return;
        }
        this.state.message = null;
        if (this.state.tabletMode) {
            return this.tabletScan(code);
        }
        const res = await this.orm.call(MODEL, "earlydryer_scan_lookup", [code], {
            branch_id: this.state.branchId,
        });
        if (!res.job_id) {
            this.state.message = { type: "danger", text: res.message };
            return;
        }
        const card = this.cardById(res.job_id);
        if (!card) {
            this.state.message = { type: "warning", text: _t("%s is not on the board (%s).", res.job_name, res.state_label || res.state) };
            return;
        }
        this.highlight(card.id);
        this.state.scanOffer = card.next_state && this.rights.move
            ? { jobId: card.id, name: card.name, next: card.next_state, label: this.stateLabel(card.next_state) }
            : null;
    }

    highlight(jobId) {
        this.state.highlightId = jobId;
        setTimeout(() => {
            document.querySelector(`.o_ed_card[data-id="${jobId}"]`)?.scrollIntoView({ block: "center", inline: "center", behavior: "smooth" });
        }, 0);
        setTimeout(() => {
            if (this.state.highlightId === jobId) {
                this.state.highlightId = false;
            }
        }, 15000);
    }

    acceptOffer() {
        const { jobId, next } = this.state.scanOffer;
        this.requestMove([jobId], next);
    }

    // ------------------------------------------------------------------
    // Production tablet
    // ------------------------------------------------------------------

    setIdentity(res) {
        this.state.identity = {
            employee_id: res.employee_id,
            name: res.name,
            avatar: res.avatar,
            token: res.token,
            idleMs: res.idle_seconds * 1000,
            expiresAt: Date.now() + res.idle_seconds * 1000,
        };
        this.state.message = { type: "success", text: res.message };
    }

    touchIdentity() {
        const identity = this.state.identity;
        if (identity) {
            identity.expiresAt = Date.now() + identity.idleMs;
        }
    }

    releaseIdentity() {
        const identity = this.state.identity;
        this.state.identity = null;
        if (identity) {
            this.orm.silent.call(MODEL, "earlydryer_tablet_release", [identity.token]);
        }
    }

    async tabletScan(code) {
        const res = await this.orm.call(MODEL, "earlydryer_tablet_scan", [
            code,
            this.state.branchId,
            this.state.targetState,
            this.state.identity?.token || false,
        ]);
        if (res.kind === "identity") {
            this.releaseIdentity();
            return this.setIdentity(res);
        }
        if (res.kind === "error") {
            if (res.relogin) {
                this.state.identity = null;
            }
            this.state.message = { type: "danger", text: res.message };
            return;
        }
        this.touchIdentity();
        this.applyCards(res);
        const result = res.results[0] || {};
        const ok = result.result === "ok" || result.result === "duplicate";
        this.state.message = {
            type: ok ? (result.warning ? "warning" : "success") : "danger",
            text: [result.message, result.warning].filter(Boolean).join(" "),
        };
        if (result.job_id) {
            this.highlight(result.job_id);
            if (!ok) {
                this.state.errors[result.job_id] = result.message;
                setTimeout(() => delete this.state.errors[result.job_id], 10000);
            }
        }
    }

    openPinPad() {
        this.state.pinPad = true;
        this.state.pin = "";
    }

    pressPin(digit) {
        if (digit === "C") {
            this.state.pin = "";
        } else if (this.state.pin.length < 12) {
            this.state.pin += digit;
        }
    }

    async submitPin() {
        const pin = this.state.pin;
        this.state.pin = "";
        const res = await this.orm.call(MODEL, "earlydryer_tablet_identify", [pin, this.state.branchId]);
        if (res.ok) {
            this.releaseIdentity();
            this.setIdentity(res);
            this.state.pinPad = false;
            this.focusScan();
        } else {
            this.state.message = { type: "danger", text: res.message };
        }
    }

    // ------------------------------------------------------------------
    // Side panel and actions
    // ------------------------------------------------------------------

    async openPanel(card) {
        this.state.panel = await this.orm.call(MODEL, "earlydryer_board_job_detail", [card.id]);
    }

    panelNext(panel) {
        this.state.panel = null;
        this.requestMove([panel.id], panel.next_state);
    }

    get currentEmployeeId() {
        return this.state.tabletMode ? this.state.identity?.employee_id || false : false;
    }

    async doServerAction(promise, jobIds) {
        const action = await promise;
        this.state.panel = null;
        if (action && typeof action === "object") {
            await this.action.doAction(action, {
                onClose: () => this.refreshCards(jobIds).then(() => this.focusScan()),
            });
        } else {
            await this.refreshCards(jobIds);
            this.focusScan();
        }
    }

    openSort(jobId) {
        return this.doServerAction(
            this.orm.call(MODEL, "earlydryer_board_open_sort", [jobId], {
                employee_id: this.currentEmployeeId,
            }),
            [jobId]
        );
    }

    openQc(jobId) {
        return this.doServerAction(
            this.orm.call(MODEL, "earlydryer_board_open_qc", [jobId], {
                employee_id: this.currentEmployeeId,
            }),
            [jobId]
        );
    }

    printBagLabel(jobId) {
        return this.doServerAction(this.orm.call(MODEL, "action_print_bag_label", [[jobId]]), [jobId]);
    }

    openJob(jobId) {
        this.state.panel = null;
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: MODEL,
            res_id: jobId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    reportBreakdown(machine) {
        if (!this.rights.breakdown) {
            return;
        }
        const promise = machine
            ? this.orm.call("maintenance.equipment", "action_earlydryer_report_breakdown", [[machine.id]])
            : Promise.resolve({
                  type: "ir.actions.act_window",
                  res_model: "earlydryer.breakdown.wizard",
                  views: [[false, "form"]],
                  target: "new",
                  context: { default_earlydryer_branch_id: this.state.branchId },
              });
        return this.doServerAction(promise, []);
    }
}

registry.category("actions").add("earlydryer_production.stage_board", EarlydryerStageBoard);
