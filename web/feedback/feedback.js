// The feedback page: sends a bug report or feature idea to Creed's server, which passes it to the creator's form.
import '@fontsource/barlow/400.css';
import '@fontsource/barlow/500.css';
import '@fontsource/barlow/600.css';
import '@fontsource/barlow-condensed/600.css';
import '@fontsource/barlow-condensed/700.css';
import '../welcome/welcome.css';
import './feedback.css';
import { inject } from '@vercel/analytics';

inject();

const $ = (id) => document.getElementById(id);
const form = $('feedback-form');
const title = $('fb-title');
const details = $('fb-details');
const device = $('fb-device');
const email = $('fb-email');
const send = $('fb-send');
const status = $('fb-status');
const sent = $('fb-sent');

// A plain guess at the device, so a bug report says where it happened. The visitor can change it.
function guessDevice() {
  const ua = navigator.userAgent;
  const os = /iPhone/.test(ua) ? 'iPhone'
    : /iPad/.test(ua) ? 'iPad'
    : /Android/.test(ua) ? 'Android'
    : /Mac OS X/.test(ua) ? 'Mac'
    : /Windows/.test(ua) ? 'Windows'
    : /Linux/.test(ua) ? 'Linux' : '';
  const browser = /Edg\//.test(ua) ? 'Edge'
    : /CriOS|Chrome\//.test(ua) ? 'Chrome'
    : /FxiOS|Firefox\//.test(ua) ? 'Firefox'
    : /Safari\//.test(ua) ? 'Safari' : '';
  const installed = window.matchMedia('(display-mode: standalone)').matches || navigator.standalone;
  return [os, installed ? 'Home-screen app' : browser].filter(Boolean).join(' · ');
}

function kind() {
  return form.querySelector('input[name="kind"]:checked')?.value || 'bug';
}

function showKind() {
  const isBug = kind() === 'bug';
  $('details-label').textContent = isBug ? 'What happened?' : 'What would you like?';
  details.placeholder = isBug
    ? 'What you did, what you expected, and what you saw instead.'
    : "What you'd like Creed to do, and how it would help your training.";
  title.placeholder = isBug ? 'e.g. Sync time stays red after a sync' : 'e.g. Show my weekly swim distance';
}

function say(text, problem = false) {
  status.textContent = text;
  status.classList.toggle('problem', problem);
}

device.value = guessDevice();
showKind();
for (const radio of form.querySelectorAll('input[name="kind"]')) radio.addEventListener('change', showKind);
details.addEventListener('input', () => {
  $('details-count').textContent = details.value.length;
});

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!title.value.trim()) {
    say('Give it a short title.', true);
    title.focus();
    return;
  }
  if (!details.value.trim()) {
    say('Add a few details.', true);
    details.focus();
    return;
  }
  if (email.value.trim() && !email.checkValidity()) {
    say("That email address doesn't look right.", true);
    email.focus();
    return;
  }
  send.disabled = true;
  say('Sending…');
  try {
    const response = await fetch('/api/public/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        kind: kind(),
        title: title.value,
        details: details.value,
        device: device.value,
        email: email.value,
        website: form.elements.website.value,
      }),
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(typeof body.detail === 'string' ? body.detail : "It didn't go through. Please try again in a minute.");
    }
    form.hidden = true;
    sent.hidden = false;
    sent.focus();
  } catch (failure) {
    say(failure instanceof TypeError ? "You seem to be offline. Try again when you're connected." : failure.message, true);
  } finally {
    send.disabled = false;
  }
});

$('fb-another').addEventListener('click', () => {
  form.reset();
  device.value = guessDevice();
  $('details-count').textContent = '0';
  showKind();
  say('');
  sent.hidden = true;
  form.hidden = false;
  title.focus();
});
