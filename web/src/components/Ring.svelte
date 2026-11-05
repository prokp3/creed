<script>
  let { value, sub, fraction = 0, label, tag, attention = false, full = false, href = '#/in-depth' } = $props();

  const RADIUS = 48;
  const CIRCUMFERENCE = 2 * Math.PI * RADIUS;
  const filled = $derived(Math.max(0, Math.min(1, fraction)) * CIRCUMFERENCE);
  const color = $derived(attention ? 'var(--attention)' : 'var(--ink)');
</script>

<a class="ring pressable" {href} aria-label={`${label} ${value} ${sub}${attention ? ', needs attention' : ''}`}>
  <svg width="112" height="112" viewBox="0 0 112 112" aria-hidden="true">
    <circle cx="56" cy="56" r={RADIUS} fill="none" stroke={full ? color : 'var(--track)'} stroke-width="8" />
    {#if !full && filled > 0}
      <circle
        cx="56"
        cy="56"
        r={RADIUS}
        fill="none"
        stroke={color}
        stroke-width="8"
        stroke-linecap="round"
        stroke-dasharray={`${filled} ${CIRCUMFERENCE}`}
        transform="rotate(-90 56 56)"
      />
    {/if}
    <text x="56" y="64" text-anchor="middle" class="value" fill={color}>{value}</text>
    <text x="56" y="80" text-anchor="middle" class="sub">{sub}</text>
  </svg>
  <span class="label" class:attention>{label}</span>
  <span class="tag">{tag}</span>
</a>

<style>
  .ring {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 2px;
  }

  .value {
    font: 800 40px var(--display);
  }

  .sub {
    font: 500 11px var(--body);
    fill: var(--ink-2);
  }

  .label {
    font: 700 16px/1.2 var(--display);
    letter-spacing: 0.05em;
    text-transform: uppercase;
    text-align: center;
  }
</style>
