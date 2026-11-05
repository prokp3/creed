<script>
  // Everything before the app opens: signing in, first-time setup, and getting back in with the recovery code.
  // Each passkey step fetches what it needs first, so the tap goes straight to Face ID. See lib/passkey.js.
  import { onDestroy, onMount, untrack } from 'svelte';
  import RecoveryCode from '../components/RecoveryCode.svelte';
  import { post } from '../lib/api.js';
  import { alreadyHasPasskey, createPasskey, deviceName, passkeyProblem, passkeysSupported, unlockName, usePasskey } from '../lib/passkey.js';

  // A challenge lasts 5 minutes on the server, so a fresh one is fetched before it runs out.
  const REFRESH_OPTIONS_MS = 4 * 60 * 1000;

  let { hasPasskey, onfinished } = $props();

  let step = $state(untrack(() => (hasPasskey ? 'sign-in' : 'secret')));
  let busy = $state(false);
  let problem = $state(null);
  let secret = $state('');
  let codeInput = $state('');
  let newCode = $state(null);
  let recovering = $state(false);
  let signInOptions = $state(null);
  let createOptions = $state(null);
  let afterCode = () => {};
  let refreshTimer;

  const supported = passkeysSupported();
  const unlock = unlockName();

  async function attempt(work) {
    busy = true;
    problem = null;
    try {
      await work();
    } catch (failure) {
      problem = passkeyProblem(failure);
    } finally {
      busy = false;
    }
  }

  async function loadSignInOptions() {
    clearTimeout(refreshTimer);
    try {
      signInOptions = await post('/api/auth/sign-in/options');
      refreshTimer = setTimeout(loadSignInOptions, REFRESH_OPTIONS_MS);
    } catch (failure) {
      problem = failure.message;
    }
  }

  function goTo(next) {
    step = next;
    problem = null;
    clearTimeout(refreshTimer);
    if (next === 'sign-in') loadSignInOptions();
  }

  const signIn = () =>
    attempt(async () => {
      try {
        const credential = await usePasskey(signInOptions);
        await post('/api/auth/sign-in/verify', { credential });
      } catch (failure) {
        // The server uses a challenge up on any answer, so the next try needs a new one.
        if (failure.status) loadSignInOptions();
        throw failure;
      }
      onfinished();
    });

  const submitSecret = (event) => {
    event.preventDefault();
    return attempt(async () => {
      createOptions = await post('/api/auth/register/options', { setup_secret: secret });
      secret = '';
      recovering = false;
      goTo('create');
    });
  };

  const makePasskey = () =>
    attempt(async () => {
      let result;
      try {
        const credential = await createPasskey(createOptions);
        result = await post('/api/auth/register/verify', { credential, label: deviceName() });
      } catch (failure) {
        if (alreadyHasPasskey(failure) && recovering) return onfinished();
        if (alreadyHasPasskey(failure)) {
          goTo('sign-in');
          throw failure;
        }
        if (failure.status) goTo(recovering ? 'recovered' : 'secret');
        throw failure;
      }
      if (result.recovery_code) {
        newCode = result.recovery_code;
        afterCode = onfinished;
        goTo('save-code');
      } else {
        onfinished();
      }
    });

  const submitCode = (event) => {
    event.preventDefault();
    return attempt(async () => {
      const result = await post('/api/auth/recover', { code: codeInput });
      codeInput = '';
      newCode = result.recovery_code;
      recovering = true;
      afterCode = () => goTo('recovered');
      goTo('save-code');
    });
  };

  const getReadyForNewPasskey = () =>
    attempt(async () => {
      createOptions = await post('/api/auth/register/options');
      goTo('create');
    });

  onMount(() => {
    if (step === 'sign-in') loadSignInOptions();
  });
  onDestroy(() => clearTimeout(refreshTimer));
</script>

<main class="page" data-no-haptics>
  <div class="brand">
    <img src="/icons/icon-192.png" alt="" width="72" height="72" />
    <h1>Creed</h1>
  </div>

  <div class="actions stack">
    {#if problem}
      <p class="attention problem" role="alert">{problem}</p>
    {/if}

    {#if step === 'sign-in'}
      {#if supported}
        <button class="primary-button pressable" disabled={busy || !signInOptions} onclick={signIn}>Sign in with {unlock}</button>
      {:else}
        <p class="note">This browser can't use passkeys. Use your recovery code instead.</p>
      {/if}
      <button class="text-button pressable" onclick={() => goTo('recover')}>Use a recovery code</button>
      <button class="text-button pressable" onclick={() => goTo('secret')}>Add a passkey with the setup secret</button>

    {:else if step === 'secret'}
      <form class="stack" onsubmit={submitSecret}>
        <h2 class="page-heading">{hasPasskey ? 'Add a passkey' : 'Set up Creed'}</h2>
        <label class="note" for="setup-secret">Enter the setup secret you added to the server.</label>
        <input id="setup-secret" class="field wide" type="password" autocomplete="off" autocapitalize="off" spellcheck="false" bind:value={secret} />
        <button class="primary-button pressable" disabled={busy || !secret.trim()}>Continue</button>
      </form>
      {#if hasPasskey}
        <button class="text-button pressable" onclick={() => goTo('sign-in')}>Back</button>
      {:else}
        <button class="text-button pressable" onclick={() => goTo('recover')}>Use a recovery code</button>
      {/if}

    {:else if step === 'create'}
      <h2 class="page-heading">{recovering ? 'Create a new passkey' : 'Create your passkey'}</h2>
      <p class="note">This device saves it, and {unlock === 'Face ID' ? 'Face ID' : 'your screen lock'} unlocks it each time you sign in.</p>
      <button class="primary-button pressable" disabled={busy || !supported} onclick={makePasskey}>Create passkey</button>
      {#if recovering}
        <button class="text-button pressable" onclick={onfinished}>Skip for now</button>
      {/if}

    {:else if step === 'save-code'}
      <h2 class="page-heading">Save your recovery code</h2>
      <p class="note">If you ever lose your passkey, this gets you back in. It works once and won't be shown again.</p>
      <RecoveryCode code={newCode} onsaved={() => afterCode()} />

    {:else if step === 'recovered'}
      <h2 class="page-heading">You're back in</h2>
      <p class="note">This session ends within an hour, so create a new passkey now.</p>
      <button class="primary-button pressable" disabled={busy} onclick={getReadyForNewPasskey}>Continue</button>
      <button class="text-button pressable" onclick={onfinished}>Skip for now</button>

    {:else if step === 'recover'}
      <form class="stack" onsubmit={submitCode}>
        <h2 class="page-heading">Use your recovery code</h2>
        <label class="note" for="recovery-code">It works once. Using it signs out every other device and gives you a new code.</label>
        <input id="recovery-code" class="field wide" type="text" autocomplete="off" autocapitalize="characters" spellcheck="false" bind:value={codeInput} />
        <button class="primary-button pressable" disabled={busy || !codeInput.trim()}>Continue</button>
      </form>
      <button class="text-button pressable" onclick={() => goTo(hasPasskey ? 'sign-in' : 'secret')}>Back</button>
    {/if}
  </div>
</main>

<style>
  .page {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    overflow-y: auto;
    padding: calc(var(--safe-top) + 16px) var(--gutter) calc(var(--safe-bottom) + 16px);
  }

  .brand {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 12px;
    min-height: 140px;
  }

  .brand img {
    border-radius: 16px;
  }

  h1 {
    font: 800 40px/1 var(--display);
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }

  .actions {
    flex: none;
    gap: 12px;
  }

  .problem {
    font-size: 14px;
  }

  .wide {
    width: 100%;
    height: 48px;
  }
</style>
