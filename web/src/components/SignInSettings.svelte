<script>
  // The Sign-in part of Settings: the passkeys, the recovery code, and signing out.
  import { del, post } from '../lib/api.js';
  import { auth, checkAuth } from '../lib/auth.svelte.js';
  import { shortDate, zonedDate } from '../lib/format.js';
  import { createPasskey, deviceName, passkeyProblem, unlockName, usePasskey } from '../lib/passkey.js';
  import { resource } from '../lib/resource.svelte.js';
  import RecoveryCode from './RecoveryCode.svelte';

  let { active, freshness, timeZone } = $props();

  const res = resource(() => '/api/auth/details');
  const unlock = unlockName();

  let problem = $state(null);
  let busy = $state(false);
  let removing = $state(null);
  let replaceOptions = $state(null);
  let newCode = $state(null);
  let createOptions = $state(null);

  const passkeys = $derived(res.data?.passkeys ?? []);
  const onRecoverySession = $derived(auth.sessionKind === 'recovery');

  $effect(() => {
    freshness;
    if (active) res.load();
  });

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

  const when = (iso) => shortDate(zonedDate(iso, timeZone));

  function describe(passkey) {
    const parts = [`Added ${when(passkey.created_at)}`];
    if (passkey.last_used_at) parts.push(`last used ${when(passkey.last_used_at)}`);
    return `${parts.join(', ')}. ${passkey.synced ? 'Synced across your devices.' : 'On this device only.'}`;
  }

  const remove = (id) =>
    attempt(async () => {
      await del(`/api/auth/passkeys/${id}`);
      removing = null;
      await res.load();
    });

  const getReadyToReplace = () =>
    attempt(async () => {
      replaceOptions = await post('/api/auth/sign-in/options');
    });

  const replaceCode = () =>
    attempt(async () => {
      try {
        const credential = await usePasskey(replaceOptions);
        const result = await post('/api/auth/recovery-code', { credential });
        newCode = result.recovery_code;
        replaceOptions = null;
        await res.load();
      } catch (failure) {
        if (failure.status) replaceOptions = null;
        throw failure;
      }
    });

  const getReadyForPasskey = () =>
    attempt(async () => {
      createOptions = await post('/api/auth/register/options');
    });

  const makePasskey = () =>
    attempt(async () => {
      try {
        const credential = await createPasskey(createOptions);
        await post('/api/auth/register/verify', { credential, label: deviceName() });
        createOptions = null;
        await checkAuth();
        await res.load();
      } catch (failure) {
        if (failure.status) createOptions = null;
        throw failure;
      }
    });

  const signOut = () =>
    attempt(async () => {
      await post('/api/auth/sign-out');
      location.hash = '#/today';
      await checkAuth();
    });
</script>

<section class="gutter stack">
  <h2 class="section-heading">Sign-in</h2>

  {#if problem}
    <div class="card attention" role="alert">{problem}</div>
  {/if}

  {#if onRecoverySession}
    <div class="card stack">
      <p class="note">You signed in with your recovery code, so this session ends within an hour. Create a new passkey to stay signed in.</p>
      {#if createOptions}
        <button class="primary-button pressable" disabled={busy} onclick={makePasskey}>Create passkey</button>
      {:else}
        <button class="primary-button pressable" disabled={busy} onclick={getReadyForPasskey}>Continue</button>
      {/if}
    </div>
  {/if}

  {#if newCode}
    <div class="card stack">
      <p class="note">Your old code no longer works. Save this one, because it won't be shown again.</p>
      <RecoveryCode code={newCode} onsaved={() => (newCode = null)} />
    </div>
  {/if}

  <div class="list">
    {#each passkeys as passkey (passkey.id)}
      <div class="list-block">
        <div class="list-inner">
          <span>{passkey.label}</span>
          {#if passkeys.length > 1 && removing !== passkey.id}
            <button class="text-button small pressable" onclick={() => (removing = passkey.id)}>Remove</button>
          {/if}
        </div>
        <p class="note">{describe(passkey)}</p>
        {#if removing === passkey.id}
          <div class="list-inner">
            <button class="text-button small attention pressable" disabled={busy} onclick={() => remove(passkey.id)}>Remove this passkey</button>
            <button class="text-button small pressable" onclick={() => (removing = null)}>Keep it</button>
          </div>
        {/if}
      </div>
    {:else}
      {#if res.data}
        <div class="list-block"><p class="note">No passkeys yet.</p></div>
      {/if}
    {/each}

    {#if res.data}
      <div class="list-block">
        <div class="list-inner">
          <span>Recovery code</span>
          {#if passkeys.length && !replaceOptions}
            <button class="text-button small pressable" disabled={busy} onclick={getReadyToReplace}>Replace</button>
          {/if}
        </div>
        <p class="note">
          {res.data.recovery_code_created_at ? `Created ${when(res.data.recovery_code_created_at)}. It's never shown again, so replace it if you've lost it.` : "You don't have one yet."}
        </p>
        {#if replaceOptions}
          <button class="primary-button pressable" disabled={busy} onclick={replaceCode}>Confirm with {unlock}</button>
          <button class="text-button small pressable" onclick={() => (replaceOptions = null)}>Keep the current code</button>
        {/if}
      </div>
    {/if}
  </div>

  <button class="secondary-button pressable" disabled={busy} onclick={signOut}>Sign out</button>
</section>

<style>
  .small {
    min-height: 32px;
    margin: -6px 0;
    padding: 6px 0;
  }
</style>
