/**
 * Offline store of the rider view (IndexedDB): the last trip data, the queue
 * of actions waiting to be sent and the photos waiting to be uploaded.
 * One database per user; nothing here is sent anywhere but to Odoo.
 */

const VERSION = 1;
const STORES = ["kv", "actions", "photos"];

export function newUuid() {
    if (window.crypto?.randomUUID) {
        return window.crypto.randomUUID();
    }
    const bytes = window.crypto.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("");
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export class RiderStore {
    constructor(userId) {
        this.name = `earlydryer_rider_${userId}`;
        this._db = null;
    }

    open() {
        if (!this._db) {
            this._db = new Promise((resolve, reject) => {
                const request = indexedDB.open(this.name, VERSION);
                request.onupgradeneeded = () => {
                    for (const store of STORES) {
                        if (!request.result.objectStoreNames.contains(store)) {
                            request.result.createObjectStore(store, { keyPath: "key" });
                        }
                    }
                };
                request.onsuccess = () => resolve(request.result);
                request.onerror = () => reject(request.error);
            });
        }
        return this._db;
    }

    async _run(store, mode, fn) {
        const db = await this.open();
        return new Promise((resolve, reject) => {
            const tx = db.transaction(store, mode);
            const request = fn(tx.objectStore(store));
            tx.oncomplete = () => resolve(request?.result);
            tx.onerror = () => reject(tx.error);
            tx.onabort = () => reject(tx.error);
        });
    }

    put(store, value) {
        // plain copy: reactive proxies cannot be cloned into IndexedDB
        return this._run(store, "readwrite", (s) => s.put(JSON.parse(JSON.stringify(value))));
    }

    delete(store, key) {
        return this._run(store, "readwrite", (s) => s.delete(key));
    }

    async all(store) {
        const rows = (await this._run(store, "readonly", (s) => s.getAll())) || [];
        return rows.sort((a, b) => (a.created || 0) - (b.created || 0));
    }

    async getValue(key, fallback = null) {
        const row = await this._run("kv", "readonly", (s) => s.get(key));
        return row ? row.value : fallback;
    }

    setValue(key, value) {
        return this.put("kv", { key, value });
    }
}
