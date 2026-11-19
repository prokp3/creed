// The Try Creed page: sends the answers to Creed's server, which passes them to the creator's form.
// "Skip the form" goes straight to the setup guide and adds one to the homepage's shared tap count.
import '@fontsource/barlow/400.css';
import '@fontsource/barlow/500.css';
import '@fontsource/barlow/600.css';
import '@fontsource/barlow-condensed/600.css';
import '@fontsource/barlow-condensed/700.css';
import '../welcome/welcome.css';
import '../feedback/feedback.css';
import './try.css';
import { inject } from '@vercel/analytics';

inject();

const $ = (id) => document.getElementById(id);
const form = $('try-form');
const name = $('t-name');
const email = $('t-email');
const send = $('t-send');
const status = $('t-status');
const sent = $('t-sent');

function choice(group) {
  return form.querySelector(`input[name="${group}"]:checked`)?.value || '';
}

function say(text, problem = false) {
  status.textContent = text;
  status.classList.toggle('problem', problem);
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!name.value.trim()) {
    say('Tell me your name.', true);
    name.focus();
    return;
  }
  if (!email.value.trim() || !email.checkValidity()) {
    say('Add your email address so I can reply.', true);
    email.focus();
    return;
  }
  if (!choice('contact')) {
    say('Let me know whether I can email you.', true);
    form.querySelector('input[name="contact"]').focus();
    return;
  }
  send.disabled = true;
  say('Sending…');
  try {
    const response = await fetch('/api/public/try-form', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: name.value,
        email: email.value,
        watch: $('t-watch').value,
        training: $('t-training').value,
        tried: choice('tried'),
        review: $('t-review').value,
        wishes: $('t-wishes').value,
        contact: choice('contact'),
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
    window.scrollTo({ top: sent.offsetTop - 80, behavior: 'smooth' });
  } catch (failure) {
    say(failure instanceof TypeError ? "You seem to be offline. Try again when you're connected." : failure.message, true);
  } finally {
    send.disabled = false;
  }
});

// Same once-per-browser rule as the homepage's "Try Creed now" button, so the two share one honest total.
const TRIED_KEY = 'creed-welcome-tried';
for (const link of document.querySelectorAll('[data-skip]')) {
  link.addEventListener('click', () => {
    try {
      if (localStorage.getItem(TRIED_KEY) === '1') return;
      localStorage.setItem(TRIED_KEY, '1');
    } catch {
      // Counted anyway, just not remembered.
    }
    fetch('/api/public/try', { method: 'POST', keepalive: true }).catch(() => {});
  });
}
