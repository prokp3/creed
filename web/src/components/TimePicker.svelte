<script>
  // A 12-hour clock picker using the phone's own wheels. It changes the time of day and keeps the date.
  import { pad2 } from '../lib/format.js';

  let { value = $bindable(), label = 'Time' } = $props();

  const HOURS = [12, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11];
  const hour = $derived(value.getHours() % 12 || 12);
  const minute = $derived(value.getMinutes());
  const period = $derived(value.getHours() < 12 ? 'AM' : 'PM');
  // Every 5 minutes, plus the exact minute it's set to now.
  const minutes = $derived([...new Set([...Array.from({ length: 12 }, (_, i) => i * 5), minute])].sort((a, b) => a - b));

  function set(nextHour, nextMinute, nextPeriod) {
    const next = new Date(value);
    next.setHours((Number(nextHour) % 12) + (nextPeriod === 'PM' ? 12 : 0), Number(nextMinute), 0, 0);
    value = next;
  }
</script>

<div class="picker" role="group" aria-label={label}>
  <select class="field" aria-label="Hour" value={hour} onchange={(e) => set(e.currentTarget.value, minute, period)}>
    {#each HOURS as h (h)}<option value={h}>{h}</option>{/each}
  </select>
  <span aria-hidden="true">:</span>
  <select class="field" aria-label="Minute" value={minute} onchange={(e) => set(hour, e.currentTarget.value, period)}>
    {#each minutes as m (m)}<option value={m}>{pad2(m)}</option>{/each}
  </select>
  <select class="field" aria-label="AM or PM" value={period} onchange={(e) => set(hour, minute, e.currentTarget.value)}>
    <option value="AM">AM</option>
    <option value="PM">PM</option>
  </select>
</div>

<style>
  .picker {
    display: flex;
    align-items: center;
    gap: 6px;
  }

  .field {
    height: 44px;
    padding: 0 10px;
  }
</style>
