<script>
  // A food ring: how much of a nutrient you've eaten against that day's target. Without a target it shows the
  // amount eaten on an empty track rather than inventing one.
  import { amountText } from '../lib/food.js';

  let { item, size = 150, color = 'var(--ink)', onclick } = $props();

  const stroke = $derived(size >= 140 ? 10 : 9);
  const radius = $derived(size / 2 - stroke / 2 - 2);
  const circumference = $derived(2 * Math.PI * radius);
  const filled = $derived(Math.min(1, Math.max(0, item.fraction)) * circumference);
  const over = $derived(item.target !== null && item.eaten > item.target);
  const unit = $derived(item.unit === 'kcal' ? 'KCAL' : item.unit.toUpperCase());

  const under = $derived.by(() => {
    if (item.target === null) return 'No target';
    const left = Math.abs(item.remaining);
    const amount = `${amountText(left, item.unit)}${item.unit === 'kcal' ? '' : ` ${item.unit}`}`;
    return over ? `${amount} over` : `${amount} left`;
  });

  const label = $derived(
    `${item.name} ${amountText(item.eaten, item.unit)}${item.target === null ? ` ${item.unit}, no target` : ` of ${amountText(item.target, item.unit)} ${item.unit}, ${under}`}${item.incomplete ? ', may be low' : ''}`,
  );
</script>

<button type="button" class="ring pressable" {onclick} aria-label={label}>
  <svg width={size} height={size} viewBox="0 0 {size} {size}" aria-hidden="true">
    <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="var(--track)" stroke-width={stroke} />
    {#if filled > 0}
      <circle
        class="arc"
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke={color}
        stroke-width={stroke}
        stroke-linecap="round"
        stroke-dasharray="{filled} {circumference}"
        transform="rotate(-90 {size / 2} {size / 2})"
      />
    {/if}
    <text x={size / 2} y={size / 2 + size * 0.033} text-anchor="middle" class="value" fill={color} style:font-size="{Math.round(size * 0.27)}px">
      {amountText(item.eaten, item.unit)}{item.incomplete ? '*' : ''}
    </text>
    <text x={size / 2} y={size / 2 + size * 0.16} text-anchor="middle" class="sub" style:font-size="{size >= 140 ? 12 : 11}px">
      {item.target === null ? unit : `OF ${amountText(item.target, item.unit)} ${unit}`}
    </text>
  </svg>
  <span class="label" style:color={color}>{item.name}</span>
  <span class="under">{under}</span>
</button>

<style>
  .ring {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 3px;
    min-width: 0;
    padding: 0;
    border: 0;
    background: transparent;
  }

  .arc {
    animation: sweep 0.8s var(--ease) both;
  }

  @keyframes sweep {
    from {
      stroke-dasharray: 0 1000;
    }
  }

  .value {
    font-family: var(--display);
    font-weight: 800;
  }

  .sub {
    font-family: var(--body);
    font-weight: 500;
    fill: var(--ink-2);
  }

  .label {
    font: 700 16px/1.2 var(--display);
    letter-spacing: 0.05em;
    text-transform: uppercase;
  }

  .under {
    font-size: 13px;
    color: var(--ink-2);
  }
</style>
