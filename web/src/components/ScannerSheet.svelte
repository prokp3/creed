<script>
  // Scan a packet's barcode, or type it. Your own food with that barcode comes up first; otherwise Open Food Facts
  // is asked for a draft to check. With no signal, you type the food in and the barcode is kept with it.
  import { onDestroy, onMount } from 'svelte';
  import Sheet from './Sheet.svelte';
  import { ApiError, get } from '../lib/api.js';
  import { food as store } from '../lib/food.svelte.js';
  import { checkDigitOk, grabFrame, openCamera, readBarcode } from '../lib/scanner.js';

  // onfound({ food }) for your own food, or onfound({ draft, note }) for a food to check and save.
  let { onclose, onfound } = $props();

  const SCAN_EVERY_MS = 180;

  let video = $state(null);
  let canvas = null;
  let stream = null;
  let timer = null;
  let stopped = false;
  let busy = false;
  let status = $state('Opening the camera…');
  let cameraProblem = $state('');
  let typed = $state('');
  let looking = $state(false);

  async function start() {
    try {
      stream = await openCamera();
      if (stopped) return stopCamera();
      video.srcObject = stream;
      await video.play();
      status = 'Point at the barcode';
      canvas = document.createElement('canvas');
      timer = setInterval(scan, SCAN_EVERY_MS);
    } catch (failure) {
      cameraProblem = failure.message;
      status = '';
    }
  }

  async function scan() {
    if (busy || looking || !video) return;
    busy = true;
    try {
      const frame = grabFrame(video, canvas);
      const code = frame ? await readBarcode(frame) : null;
      if (code) {
        navigator.vibrate?.(30);
        await lookUp(code);
      }
    } catch {
      // A frame the reader couldn't use: try the next one.
    } finally {
      busy = false;
    }
  }

  function stopCamera() {
    clearInterval(timer);
    stream?.getTracks().forEach((track) => track.stop());
    stream = null;
  }

  async function lookUp(code) {
    looking = true;
    status = `Looking up ${code}…`;
    stopCamera();
    const mine = (store.library?.foods ?? []).find((f) => f.barcode === code);
    if (mine) return onfound({ food: mine });
    try {
      const result = await get(`/api/food/barcode/${code}`);
      if (result.source === 'library') return onfound({ food: result.food });
      if (result.source === 'openfoodfacts') {
        return onfound({ draft: result.draft, note: 'Found in Open Food Facts. Check the values against the label, then save.' });
      }
      return onfound({ draft: { barcode: code }, note: `${code} isn't in Open Food Facts. Type the food in from the label; the barcode is saved with it.` });
    } catch (failure) {
      const offline = failure instanceof ApiError && failure.status === 0;
      return onfound({
        draft: { barcode: code },
        note: offline
          ? `No connection, so ${code} couldn't be looked up. Type the food in from the label; the barcode is saved with it.`
          : failure.message,
      });
    }
  }

  function submitTyped() {
    const code = typed.replace(/\s/g, '');
    if (!/^\d{6,14}$/.test(code)) {
      cameraProblem = 'A barcode is 6 to 14 digits.';
      return;
    }
    if (!checkDigitOk(code)) {
      cameraProblem = "That number's last digit doesn't check out. Look again at the barcode.";
      return;
    }
    lookUp(code);
  }

  onMount(start);
  onDestroy(() => {
    stopped = true;
    stopCamera();
  });
</script>

<Sheet label="Scan a barcode" {onclose} tall>
  <h2 class="sheet-title">Scan a barcode</h2>

  <div class="viewfinder">
    <!-- svelte-ignore a11y_media_has_caption -->
    <video bind:this={video} playsinline muted autoplay></video>
    {#if !cameraProblem}<span class="guide" aria-hidden="true"></span>{/if}
    {#if status}<span class="status" role="status">{status}</span>{/if}
  </div>

  {#if cameraProblem}<p class="note" role="alert">{cameraProblem}</p>{/if}

  <div class="stack">
    <span class="caption">Or type the number under the barcode</span>
    <div class="typed">
      <input class="field" type="text" inputmode="numeric" maxlength="16" placeholder="8901234567890" aria-label="Barcode number" bind:value={typed} disabled={looking} />
      <button type="button" class="primary-button look pressable" disabled={looking} onclick={submitTyped}>Look up</button>
    </div>
  </div>
  <p class="note">Barcodes are read on your phone. Only the number goes to Creed, which asks Open Food Facts for you.</p>
</Sheet>

<style>
  .sheet-title {
    padding-top: 6px;
    font: 800 26px/1.1 var(--display);
    letter-spacing: 0.03em;
    text-transform: uppercase;
  }

  .viewfinder {
    position: relative;
    overflow: hidden;
    aspect-ratio: 4 / 3;
    border-radius: 14px;
    background: var(--bg);
  }

  video {
    width: 100%;
    height: 100%;
    object-fit: cover;
  }

  .guide {
    position: absolute;
    left: 5%;
    right: 5%;
    top: 25%;
    bottom: 25%;
    border: 2px solid var(--ink);
    border-radius: 10px;
    box-shadow: 0 0 0 999px rgba(0, 0, 0, 0.35);
  }

  .status {
    position: absolute;
    left: 0;
    right: 0;
    bottom: 10px;
    text-align: center;
    font-size: 13px;
    color: var(--ink);
    text-shadow: 0 1px 3px rgba(0, 0, 0, 0.9);
  }

  .caption {
    font: 700 13px/1 var(--display);
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--ink-3);
  }

  .typed {
    display: flex;
    gap: 8px;
  }

  .typed .field {
    flex: 1;
    min-width: 0;
    height: 52px;
  }

  .look {
    width: auto;
    padding: 0 18px;
  }
</style>
