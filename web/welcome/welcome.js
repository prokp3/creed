// Creed's public homepage: the visitor's own race countdown, scroll reveals, and the "Try Creed" form links.
import '@fontsource/barlow/400.css';
import '@fontsource/barlow/500.css';
import '@fontsource/barlow/600.css';
import '@fontsource/barlow-condensed/500.css';
import '@fontsource/barlow-condensed/600.css';
import '@fontsource/barlow-condensed/700.css';
import './welcome.css';

// "Try Creed" opens the site's own Try page, which passes the answers to the creator's Google Form. Without the
// script the buttons scroll to the Try section instead.
const TRY_PAGE = '/try/';
for (const link of document.querySelectorAll('[data-form]')) link.href = TRY_PAGE;
document.getElementById('form-open')?.removeAttribute('hidden');
document.getElementById('form-soon')?.setAttribute('hidden', '');

// ---- The visitor's race countdown -------------------------------------------------------------------------
// Kept only in this browser, so a returning visitor sees their own race. Storage can be unavailable (private
// windows, blocked site data), and the countdown still works for the visit.
const KEY = 'creed-welcome-race';
const DISTANCES = {
  sprint: [0.75, 20, 5],
  olympic: [1.5, 40, 10],
  half: [1.9, 90, 21.1],
  full: [3.8, 180, 42.2],
};
// A first-time visitor sees a countdown already running, to a made-up race 8 to 40 weeks away with a typical
// early start. It's labelled as an example and isn't saved, so it changes each visit until they set their own.
const EXAMPLE_WEEKS = [8, 40];
const EXAMPLE_STARTS = ['05:45', '06:00', '06:15', '06:30', '06:45', '07:00', '07:15', '07:30'];
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

const $ = (id) => document.getElementById(id);
const dateInput = $('race-date');
const timeInput = $('race-time');
const distInput = $('race-dist');
const digits = $('digits');
const parts = { d: $('cd-d'), h: $('cd-h'), m: $('cd-m'), s: $('cd-s') };
const label = $('race-label');
const tick = $('cd-tick');

function load() {
  try {
    return JSON.parse(localStorage.getItem(KEY) || 'null');
  } catch {
    return null;
  }
}

function save(value) {
  try {
    localStorage.setItem(KEY, JSON.stringify(value));
  } catch {
    // Nothing to do: the countdown just won't be remembered next time.
  }
}

function pad(n) {
  return String(n).padStart(2, '0');
}

function target() {
  if (!dateInput.value) return null;
  const [y, mo, d] = dateInput.value.split('-').map(Number);
  const [hh, mm] = (timeInput.value || '06:30').split(':').map(Number);
  const when = new Date(y, mo - 1, d, hh, mm);
  return Number.isNaN(when.getTime()) ? null : when;
}

function setExampleRace() {
  const [low, high] = EXAMPLE_WEEKS;
  const days = low * 7 + Math.floor(Math.random() * (high - low) * 7);
  const when = new Date();
  when.setDate(when.getDate() + days);
  dateInput.value = `${when.getFullYear()}-${pad(when.getMonth() + 1)}-${pad(when.getDate())}`;
  timeInput.value = EXAMPLE_STARTS[Math.floor(Math.random() * EXAMPLE_STARTS.length)];
}

let isExample = false;

function showDistances() {
  const [swim, bike, run] = DISTANCES[distInput.value] || DISTANCES.half;
  $('dist-swim').textContent = swim;
  $('dist-bike').textContent = bike;
  $('dist-run').textContent = run;
}

function render() {
  const when = target();
  if (!when) {
    digits.classList.add('empty');
    for (const el of Object.values(parts)) el.textContent = '--';
    label.textContent = 'Pick your race day';
    tick.classList.add('idle');
    return;
  }
  digits.classList.remove('empty');
  let ms = Math.max(0, when - Date.now());
  const d = Math.floor(ms / 86400000);
  ms -= d * 86400000;
  const h = Math.floor(ms / 3600000);
  ms -= h * 3600000;
  const m = Math.floor(ms / 60000);
  ms -= m * 60000;
  const s = Math.floor(ms / 1000);
  parts.d.textContent = d;
  parts.h.textContent = pad(h);
  parts.m.textContent = pad(m);
  parts.s.textContent = pad(s);
  const dateText = `${pad(when.getDate())} ${MONTHS[when.getMonth()]} ${when.getFullYear()}`;
  if (isExample) label.textContent = `Example race · ${dateText} · Change it to yours`;
  else label.textContent = when - Date.now() > 0 ? `Race day · ${dateText}` : `Race day · ${dateText} · Go get it`;
  tick.classList.toggle('idle', when - Date.now() <= 0);
}

function remember() {
  isExample = false;
  save({ date: dateInput.value, time: timeInput.value, dist: distInput.value });
  showDistances();
  render();
}

// Nothing before today.
const today = new Date();
dateInput.min = `${today.getFullYear()}-${pad(today.getMonth() + 1)}-${pad(today.getDate())}`;

const saved = load();
if (saved && typeof saved === 'object') {
  if (typeof saved.date === 'string') dateInput.value = saved.date;
  if (typeof saved.time === 'string' && saved.time) timeInput.value = saved.time;
  if (saved.dist in DISTANCES) distInput.value = saved.dist;
}
if (!dateInput.value) {
  setExampleRace();
  isExample = true;
}
for (const input of [dateInput, timeInput, distInput]) input.addEventListener('input', remember);
showDistances();
render();
setInterval(render, 1000);

// ---- "Try Creed now": a shared count of taps ------------------------------------------------------------
// The server keeps one total. Each browser adds to it once, so refreshing and tapping again doesn't inflate it.
const TRIED_KEY = 'creed-welcome-tried';
const tryNow = $('try-now');
const tryCount = $('try-count');
const tryLabel = $('try-count-label');

function showCount(count) {
  if (!Number.isFinite(count)) return;
  tryCount.textContent = count.toLocaleString('en-IN');
  tryLabel.textContent = count === 1 ? 'athlete has tapped this' : 'athletes have tapped this';
}

function alreadyTried() {
  try {
    return localStorage.getItem(TRIED_KEY) === '1';
  } catch {
    return false;
  }
}

fetch('/api/public/try')
  .then((r) => (r.ok ? r.json() : null))
  .then((data) => data && showCount(data.count))
  .catch(() => {});

tryNow.addEventListener('click', () => {
  if (alreadyTried()) return;
  try {
    localStorage.setItem(TRIED_KEY, '1');
  } catch {
    // Counted anyway, just not remembered.
  }
  fetch('/api/public/try', { method: 'POST', keepalive: true })
    .then((r) => (r.ok ? r.json() : null))
    .then((data) => data && showCount(data.count))
    .catch(() => {});
});

// ---- Scroll reveals ---------------------------------------------------------------------------------------
if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches && 'IntersectionObserver' in window) {
  document.documentElement.classList.add('motion');
  const io = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          entry.target.classList.add('in');
          io.unobserve(entry.target);
        }
      }
    },
    { threshold: 0.12 },
  );
  requestAnimationFrame(() => document.querySelectorAll('.reveal').forEach((el) => io.observe(el)));
}

$('year').textContent = new Date().getFullYear();
