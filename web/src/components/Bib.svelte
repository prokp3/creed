<script>
  import { longDate, zoneAbbreviation } from '../lib/format.js';
  import { race } from '../lib/race.svelte.js';

  const when = $derived(race.date ? `${longDate(race.date)} · ${zoneAbbreviation(race.timeZone)}` : '');
  const label = $derived(
    race.date
      ? `Race countdown: ${race.parts.days} days, ${race.parts.hours} hours, ${race.parts.minutes} minutes.`
      : 'Race countdown',
  );
</script>

<section class="bib" aria-label={label}>
  <div class="band">
    <span class="race">70.3 GOA</span>
    <span class="when">{when}</span>
  </div>
  <div class="digits" aria-hidden="true">
    <div class="unit first">
      <span class="big">{race.parts.days}</span>
      <span class="name">DAYS</span>
    </div>
    <div class="unit"><span class="mid">{race.parts.hours}</span><span class="name">HRS</span></div>
    <div class="unit"><span class="mid">{race.parts.minutes}</span><span class="name">MIN</span></div>
    <div class="unit"><span class="mid">{race.parts.seconds}</span><span class="name">SEC</span></div>
  </div>
  <i class="pin tl"></i><i class="pin tr"></i><i class="pin bl"></i><i class="pin br"></i>
</section>

<style>
  .bib {
    position: relative;
    margin: 0 var(--gutter);
    border-radius: 6px;
    overflow: hidden;
    background: var(--paper);
    color: var(--paper-ink);
  }

  .band {
    display: flex;
    align-items: center;
    justify-content: space-between;
    height: 28px;
    padding: 0 28px;
    background: var(--brand);
    color: #fff;
  }

  .race {
    font: 800 19px/1 var(--display);
    letter-spacing: 0.05em;
  }

  .when {
    font: 600 13px/1 var(--display);
    letter-spacing: 0.06em;
  }

  .digits {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    padding: 6px 24px 10px;
  }

  .unit {
    display: flex;
    flex-direction: column;
    align-items: center;
    min-width: 48px;
  }

  .unit.first {
    align-items: flex-start;
  }

  .big {
    font: 800 66px/0.95 var(--display);
  }

  .mid {
    font: 800 44px/0.95 var(--display);
    font-variant-numeric: tabular-nums;
  }

  .name {
    font: 700 12px/1.3 var(--display);
    letter-spacing: 0.1em;
    color: var(--paper-ink-2);
  }

  .pin {
    position: absolute;
    width: 9px;
    height: 9px;
    border-radius: 50%;
    background: var(--bg);
  }

  .tl { left: 8px; top: 36px; }
  .tr { right: 8px; top: 36px; }
  .bl { left: 8px; bottom: 8px; }
  .br { right: 8px; bottom: 8px; }
</style>
