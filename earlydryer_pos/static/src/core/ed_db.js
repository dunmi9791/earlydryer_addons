/**
 * Small IndexedDB store of the laundry counter, next to core POS's own:
 * condition photos (never in the order payload), queued collections and the
 * last collection cache. One database per till.
 */

const VERSION = 1;
const STORES = ["photos", "kv"];

export class EdDB {
    constructor(configId) {
        this.name = `earlydryer_pos_${configId}`;
        this._db = null;
    }

    open() {
        if (this._db) {
            return this._db;
        }
        this._db = new Promise((resolve, reject) => {
            const request = indexedDB.open(this.name, VERSION);
            request.onupgradeneeded = () => {
                const db = request.result;
                for (const store of STORES) {
                    if (!db.objectStoreNames.contains(store)) {
                        db.createObjectStore(store, { keyPath: "key" });
                    }
                }
            };
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error);
        });
        return this._db;
    }

    async _run(store, mode, fn) {
        const db = await this.open();
        return new Promise((resolve, reject) => {
            const tx = db.transaction(store, mode);
            const result = fn(tx.objectStore(store));
            tx.oncomplete = () => resolve(result?.result);
            tx.onerror = () => reject(tx.error);
            tx.onabort = () => reject(tx.error);
        });
    }

    put(store, value) {
        return this._run(store, "readwrite", (s) => s.put(value));
    }

    get(store, key) {
        return this._run(store, "readonly", (s) => s.get(key));
    }

    delete(store, key) {
        return this._run(store, "readwrite", (s) => s.delete(key));
    }

    getAll(store) {
        return this._run(store, "readonly", (s) => s.getAll());
    }

    async getValue(key, fallback = null) {
        const row = await this.get("kv", key);
        return row ? row.value : fallback;
    }

    setValue(key, value) {
        // plain copy: reactive (Proxy) values cannot be cloned into IndexedDB
        return this.put("kv", { key, value: JSON.parse(JSON.stringify(value)) });
    }
}
