import { Component, onMounted, useRef } from "@odoo/owl";

/**
 * Minimal signature canvas (works offline, unlike lazily loaded libraries).
 * Calls props.onChange(dataUrl | false) after each stroke.
 */
export class SignaturePad extends Component {
    static template = "earlydryer_logistics.SignaturePad";
    static props = { onChange: Function };

    setup() {
        this.canvasRef = useRef("canvas");
        this.drawing = false;
        this.empty = true;
        onMounted(() => this.resize());
    }

    resize() {
        const canvas = this.canvasRef.el;
        const ratio = window.devicePixelRatio || 1;
        canvas.width = canvas.offsetWidth * ratio;
        canvas.height = canvas.offsetHeight * ratio;
        const ctx = canvas.getContext("2d");
        ctx.scale(ratio, ratio);
        ctx.lineWidth = 2.2;
        ctx.lineCap = "round";
        ctx.strokeStyle = "#111";
        ctx.fillStyle = "#fff";
        ctx.fillRect(0, 0, canvas.width, canvas.height);
    }

    point(ev) {
        const rect = this.canvasRef.el.getBoundingClientRect();
        return { x: ev.clientX - rect.left, y: ev.clientY - rect.top };
    }

    onDown(ev) {
        ev.preventDefault();
        this.drawing = true;
        this.canvasRef.el.setPointerCapture?.(ev.pointerId);
        const { x, y } = this.point(ev);
        const ctx = this.canvasRef.el.getContext("2d");
        ctx.beginPath();
        ctx.moveTo(x, y);
    }

    onMove(ev) {
        if (!this.drawing) {
            return;
        }
        ev.preventDefault();
        const { x, y } = this.point(ev);
        const ctx = this.canvasRef.el.getContext("2d");
        ctx.lineTo(x, y);
        ctx.stroke();
        this.empty = false;
    }

    onUp() {
        if (!this.drawing) {
            return;
        }
        this.drawing = false;
        this.props.onChange(this.empty ? false : this.canvasRef.el.toDataURL("image/png"));
    }

    clear() {
        this.empty = true;
        this.resize();
        this.props.onChange(false);
    }
}
