// Reading food barcodes from the camera. iPhone's Safari has no built-in barcode reader for web pages, so this uses
// ZXing compiled to WebAssembly, served from Creed itself (never a CDN) and loaded only when the scanner opens.
// Reading happens on the phone; only the barcode number is ever sent anywhere.

const FORMATS = ['EAN13', 'EAN8', 'UPCA', 'UPCE'];
let reader = null;

async function load() {
  if (!reader) {
    reader = (async () => {
      const [{ prepareZXingModule, readBarcodes }, { default: wasmUrl }] = await Promise.all([
        import('zxing-wasm/reader'),
        import('zxing-wasm/reader/zxing_reader.wasm?url'),
      ]);
      prepareZXingModule({
        overrides: { locateFile: (path, prefix) => (path.endsWith('.wasm') ? wasmUrl : prefix + path) },
        fireImmediately: true,
      });
      return readBarcodes;
    })();
    reader.catch(() => {
      reader = null;
    });
  }
  return reader;
}

/** The first food barcode in an image (ImageData or a photo file), or null. */
export async function readBarcode(image) {
  const readBarcodes = await load();
  const results = await readBarcodes(image, { formats: FORMATS, tryHarder: true, maxNumberOfSymbols: 1 });
  const found = results.find((r) => r.isValid && /^\d{6,14}$/.test(r.text));
  return found ? found.text : null;
}

/** Start loading the reader early, such as when the add sheet opens. */
export function warmUp() {
  load().catch(() => {});
}

/** The back camera, as a stream for a <video>. Throws a message to show when it can't. */
export async function openCamera() {
  if (!navigator.mediaDevices?.getUserMedia) throw new Error("This browser can't use the camera here. Type the barcode instead.");
  try {
    return await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 }, height: { ideal: 720 } },
    });
  } catch (failure) {
    if (failure?.name === 'NotAllowedError') {
      throw new Error('Camera access is off for Creed. Allow it in Settings, or type the barcode instead.');
    }
    throw new Error("Couldn't open the camera. Type the barcode instead.");
  }
}

/** The middle band of a video frame, where the guide box is, as ImageData for the reader. */
export function grabFrame(video, canvas) {
  const width = video.videoWidth;
  const height = video.videoHeight;
  if (!width || !height) return null;
  const cropWidth = Math.round(width * 0.9);
  const cropHeight = Math.round(Math.min(height, width) * 0.5);
  const x = Math.round((width - cropWidth) / 2);
  const y = Math.round((height - cropHeight) / 2);
  canvas.width = cropWidth;
  canvas.height = cropHeight;
  const context = canvas.getContext('2d', { willReadFrequently: true });
  context.drawImage(video, x, y, cropWidth, cropHeight, 0, 0, cropWidth, cropHeight);
  return context.getImageData(0, 0, cropWidth, cropHeight);
}

/** EAN-13, EAN-8, UPC-A and UPC-E end in a check digit; a typed number that fails it is probably a typo. */
export function checkDigitOk(code) {
  if (!/^\d+$/.test(code) || ![8, 12, 13, 14].includes(code.length)) return true;
  const digits = code.split('').map(Number);
  const check = digits.pop();
  const sum = digits.reverse().reduce((total, d, i) => total + d * (i % 2 === 0 ? 3 : 1), 0);
  return (10 - (sum % 10)) % 10 === check;
}
