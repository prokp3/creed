import { get } from './api.js';
import { countdownParts } from './format.js';

// One countdown for every screen, ticking every second on this device's clock.
let deadline = $state(null);
let raceDate = $state(null);
let timeZone = $state(null);
let now = $state(Date.now());

setInterval(() => {
  now = Date.now();
}, 1000);

export async function refreshRace() {
  try {
    const race = await get('/api/race');
    deadline = Date.now() + race.countdown.total_seconds * 1000;
    raceDate = race.race_date;
    timeZone = race.timezone;
  } catch {
    // The bib keeps its dashes until the server can be reached.
  }
}

export const race = {
  get date() {
    return raceDate;
  },
  get timeZone() {
    return timeZone;
  },
  get parts() {
    return deadline === null
      ? { days: '—', hours: '—', minutes: '—', seconds: '—' }
      : countdownParts((deadline - now) / 1000);
  },
};
