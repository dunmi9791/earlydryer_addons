import { Component, onMounted, onWillStart, useRef, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useBus, useService } from "@web/core/utils/hooks";
import { url } from "@web/core/utils/urls";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const MODEL = "laundry.job";
const MISMATCHES = ["wrong_job", "wrong_branch"];

/**
 * Scan screen: Find, Move and Pack with a keyboard-wedge barcode scanner.
 *
 * Scanners type the code and send Enter, so a plain input that keeps the
 * focus is enough. Scans arriving while the focus is elsewhere are caught
 * through the barcode service of the `barcodes` module.
 */
export class EarlydryerScanScreen extends Component {
    static template = "earlydryer_tagging.ScanScreen";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.inputRef = useRef("scanInput");
        this.state = useState({
            mode: "find",
            branchId: false,
            employeeId: false,
            targetState: "",
            note: "",
            busy: false,
            card: null,
            message: null,
            moves: [],
            pack: null,
            packLog: [],
            alert: null,
            switchTo: null,
            missingNote: "",
        });
        this.queue = [];
        this.processing = false;
        const barcode = useService("barcode");
        useBus(barcode.bus, "barcode_scanned", (ev) => this.onScan(ev.detail.barcode));
        onWillStart(async () => {
            this.ctx = await this.orm.call(MODEL, "earlydryer_scan_context", []);
            this.state.branchId = this.ctx.default_branch_id;
            this.state.employeeId = this.ctx.default_employee_id;
            const ext = new Audio().canPlayType("audio/ogg") ? "ogg" : "mp3";
            this.sounds = {
                error: new Audio(url(`/barcodes/static/src/audio/error.${ext}`)),
                ok: new Audio(url(`/mail/static/src/audio/ting.${ext}`)),
            };
        });
        onMounted(() => this.focus());
    }

    // ------------------------------------------------------------------
    // Helpers
    // ------------------------------------------------------------------

    get branch() {
        return this.ctx.branches.find((b) => b.id === this.state.branchId) || {};
    }

    get employees() {
        const branchId = this.state.branchId;
        return this.ctx.employees.filter((e) => !branchId || e.branch_id === branchId);
    }

    get modes() {
        const rights = this.ctx.rights;
        return [
            { key: "find", label: _t("Find"), allowed: rights.find },
            { key: "move", label: _t("Move"), allowed: rights.move },
            { key: "pack", label: _t("Pack"), allowed: rights.pack },
        ].filter((m) => m.allowed);
    }

    get pendingMoves() {
        return this.state.moves.filter((m) => m.result === "pending");
    }

    focus() {
        if (this.state.alert) {
            return;
        }
        // let OWL patch the DOM first
        setTimeout(() => this.inputRef.el?.focus(), 0);
    }

    play(sound) {
        const audio = this.sounds?.[sound];
        if (audio) {
            audio.currentTime = 0;
            audio.play().catch(() => {});
        }
    }

    setMode(mode) {
        Object.assign(this.state, {
            mode,
            card: null,
            message: null,
            alert: null,
            switchTo: null,
        });
        this.focus();
    }

    async call(method, args, kwargs = {}) {
        this.state.busy = true;
        try {
            return await this.orm.call(MODEL, method, args, kwargs);
        } finally {
            this.state.busy = false;
            this.focus();
        }
    }

    // ------------------------------------------------------------------
    // Input
    // ------------------------------------------------------------------

    onKeydown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            // uncontrolled input: a scanner may type the next code at once
            const code = ev.target.value;
            ev.target.value = "";
            this.onScan(code);
        }
    }

    onBlur() {
        // keep the scanner input focused unless another control took the focus
        setTimeout(() => {
            const active = document.activeElement;
            if (!active || active === document.body) {
                this.focus();
            }
        }, 150);
    }

    onScan(rawCode) {
        const code = (rawCode || "").trim().toUpperCase();
        if (!code) {
            return;
        }
        // scans arriving while the server answers are handled in order
        this.queue.push(code);
        if (!this.processing) {
            this.processQueue();
        }
    }

    async processQueue() {
        this.processing = true;
        try {
            while (this.queue.length) {
                if (this.state.alert) {
                    // a blocking alert stops the queue until acknowledged
                    return;
                }
                const code = this.queue.shift();
                if (this.state.mode === "find") {
                    await this.find(code);
                } else if (this.state.mode === "move") {
                    await this.scanMove(code);
                } else {
                    await this.scanPack(code);
                }
            }
        } catch (error) {
            this.queue = [];
            this.play("error");
            throw error;
        } finally {
            this.processing = false;
        }
    }

    // ------------------------------------------------------------------
    // Find
    // ------------------------------------------------------------------

    async find(code) {
        const res = await this.call("earlydryer_scan_lookup", [code], {
            branch_id: this.state.branchId,
        });
        if (res.type === "item" || res.type === "job") {
            this.state.card = res;
            this.state.message = null;
            this.play("ok");
        } else {
            this.state.card = null;
            this.state.message = { type: "danger", text: res.message };
            this.play("error");
        }
    }

    openJob(jobId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: MODEL,
            res_id: jobId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    // ------------------------------------------------------------------
    // Move
    // ------------------------------------------------------------------

    async scanMove(code) {
        if (!this.state.targetState) {
            this.play("error");
            this.state.message = { type: "warning", text: _t("Choose the stage first.") };
            return;
        }
        if (this.state.moves.some((m) => m.code === code && m.result === "pending")) {
            this.play("error");
            this.state.message = { type: "warning", text: _t("%s already scanned.", code) };
            return;
        }
        this.state.message = null;
        if (this.branch.commit_per_scan) {
            await this.commitMoves([code]);
            return;
        }
        const res = await this.call("earlydryer_scan_lookup", [code], {
            branch_id: this.state.branchId,
            log: false,
        });
        const valid = res.type === "item" || res.type === "job";
        this.state.moves.unshift({
            code,
            result: valid ? "pending" : res.type,
            job_name: res.job_name,
            message: valid ? _t("To move (now %s)", res.state_label) : res.message,
            warning: "",
        });
        this.play(valid ? "ok" : "error");
    }

    async commitMoves(codes) {
        codes = codes || this.pendingMoves.map((m) => m.code);
        if (!codes.length) {
            return;
        }
        const results = await this.call("earlydryer_scan_move", [
            codes,
            this.state.targetState,
            this.state.employeeId || false,
        ], { note: this.state.note || false });
        const byCode = Object.fromEntries(results.map((r) => [r.code, r]));
        const kept = this.state.moves.filter((m) => !byCode[m.code] || m.result !== "pending");
        this.state.moves = [...results.reverse(), ...kept];
        const failed = results.some((r) => r.result !== "ok" && r.result !== "duplicate");
        this.play(failed ? "error" : "ok");
    }

    clearMoves() {
        this.state.moves = [];
        this.focus();
    }

    // ------------------------------------------------------------------
    // Pack
    // ------------------------------------------------------------------

    async startPack(code) {
        const res = await this.call("earlydryer_pack_start", [code]);
        if (res.result !== "ok") {
            this.state.message = { type: "danger", text: res.message };
            this.play("error");
            return;
        }
        this.state.pack = res;
        this.state.packLog = [];
        this.state.switchTo = null;
        this.state.message = null;
        this.play("ok");
    }

    async scanPack(code) {
        if (!this.state.pack) {
            return this.startPack(code);
        }
        const res = await this.call("earlydryer_scan_pack", [this.state.pack.job_id, code], {
            employee_id: this.state.employeeId || false,
        });
        this.state.pack = { ...this.state.pack, ...res };
        this.state.packLog.unshift(res);
        this.state.switchTo = null;
        if (res.bag && res.result === "wrong_job") {
            // another bag label: offer to switch, no alarm
            this.state.switchTo = { code, name: res.other_job_name };
            this.play("error");
        } else if (MISMATCHES.includes(res.result)) {
            this.state.alert = res;
            this.play("error");
        } else if (res.result === "ok") {
            this.play("ok");
        } else {
            this.play("error");
        }
    }

    acknowledgeAlert() {
        this.state.alert = null;
        this.focus();
        if (this.queue.length && !this.processing) {
            this.processQueue();
        }
    }

    async switchJob() {
        const code = this.state.switchTo.code;
        this.state.pack = null;
        await this.startPack(code);
    }

    closePack() {
        this.state.pack = null;
        this.state.packLog = [];
        this.state.switchTo = null;
        this.focus();
    }

    async finishPack(markMissing = false) {
        const res = await this.call(
            "earlydryer_pack_finish",
            [this.state.pack.job_id, this.state.employeeId || false],
            { note: markMissing ? this.state.missingNote : false, mark_missing: markMissing }
        );
        this.notification.add(res.message, {
            type: res.result === "ok" ? "success" : "warning",
        });
        if (res.result === "ok") {
            this.closePack();
        } else {
            this.state.pack = { ...this.state.pack, ...res };
            this.state.missingNote = "";
        }
    }

    resultClass(result) {
        return (
            {
                ok: "text-bg-success",
                pending: "text-bg-info",
                duplicate: "text-bg-warning",
                refused: "text-bg-danger",
                wrong_job: "text-bg-danger",
                wrong_branch: "text-bg-danger",
                invalid: "text-bg-danger",
                unknown: "text-bg-secondary",
            }[result] || "text-bg-secondary"
        );
    }
}

registry.category("actions").add("earlydryer_tagging.scan_screen", EarlydryerScanScreen);
