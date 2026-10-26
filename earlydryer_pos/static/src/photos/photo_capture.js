/**
 * Resize and compress a camera picture in the browser: longest side 1280 px,
 * JPEG quality 0.7 (about 150 KB). Returns the base64 data without prefix.
 */
export const MAX_SIDE = 1280;
export const QUALITY = 0.7;

function loadImage(file) {
    return new Promise((resolve, reject) => {
        const url = URL.createObjectURL(file);
        const img = new Image();
        img.onload = () => {
            URL.revokeObjectURL(url);
            resolve(img);
        };
        img.onerror = (error) => {
            URL.revokeObjectURL(url);
            reject(error);
        };
        img.src = url;
    });
}

export async function compressPhoto(file, maxSide = MAX_SIDE, quality = QUALITY) {
    const img = await loadImage(file);
    const scale = Math.min(1, maxSide / Math.max(img.naturalWidth, img.naturalHeight));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(img.naturalWidth * scale);
    canvas.height = Math.round(img.naturalHeight * scale);
    canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL("image/jpeg", quality).split(",")[1];
}
