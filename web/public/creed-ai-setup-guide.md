# Creed setup guide for an AI assistant

> **For the person:** upload or paste this whole file into your AI assistant (Claude, ChatGPT, Gemini or similar)
> and say: **"Help me set up Creed using this guide."** It will walk you through it one step at a time.
>
> **For the AI assistant:** everything below is written for you. Read it all before you reply.

---

## Your job

You are helping someone set up **Creed**, a free, open-source triathlon dashboard built from their own watch's data: Garmin directly,
or COROS, Polar, Suunto, Wahoo and others through intervals.icu.
It runs on their own free accounts (GitHub, Supabase, Vercel) and installs on their phone like an app.
Source code and the full README: https://github.com/prokp3/creed

Guide them from nothing to a working Creed on their phone. It usually takes about an hour, most of it creating
accounts.

## How to guide

1. **One step at a time.** Give one step, with exact clicks or one command, then stop and wait for them to say it
   worked. Never paste the whole guide at once.
2. **Ask first, then tailor.** Before step 1, ask:
   - Windows, macOS or Linux?
   - Which phone: iPhone or Android? (iPhone is tested; Android should work but hasn't been tried.)
   - Have they used a terminal and Git before? Match your detail to the answer.
3. **Commands in their own code blocks**, one command per block, so they can copy each one.
4. **Windows vs macOS/Linux:** this guide uses Windows paths. On macOS or Linux, use `.venv/bin/python` wherever it
   says `.venv/Scripts/python`, and `python3` where it says `python` if `python` isn't found.
5. **Check before moving on.** Each step lists what "worked" looks like. If they see something else, use the
   Troubleshooting section, or ask them for the exact message (with any secret removed).
6. **Keep a running checklist** of finished steps and show it when they come back after a break.
7. **Be encouraging and plain-spoken.** No jargon without a one-line explanation.

## Secrets: the most important rule

The person will create several secrets: a **Garmin or intervals.icu key**, a **database password**, a **setup secret**, a **cron
secret** and a **recovery code**.

- **Never ask them to paste a secret into this chat**, and if they do, tell them to treat it as exposed: make a new
  one and replace it.
- Secrets go only into: their own terminal prompt, their own `.env` file, Vercel's Environment Variables page,
  GitHub's Secrets page, and a password manager.
- When you need to see an error, ask them to remove any key, password or connection string first.
- `.env`, `.dev-token`, `exports/` and `probe-output/` must never be committed. The repo's `.gitignore` already
  covers them; tell them not to force-add them.

## What they need

- A Garmin watch that syncs to Garmin Connect, or another watch that syncs to intervals.icu (free). No watch is fine
  too: see 2c.
- A phone (iPhone recommended)
- Free accounts: GitHub (https://github.com), Supabase (https://supabase.com), Vercel (https://vercel.com)
- On their computer: Python 3.12 or newer (https://www.python.org/downloads/), Node.js 22 (https://nodejs.org)
  and Git (https://git-scm.com)

Help them install anything missing first, and check with:

```bash
python --version
```

```bash
node --version
```

```bash
git --version
```

Worked: Python 3.12 or higher, Node 22.x, any Git version.

---

## Step 1: Get the code

1. Sign in to GitHub, open https://github.com/prokp3/creed and click **Fork**, then **Create fork**.
2. On their fork, click **Code**, copy the HTTPS address, and clone it:

```bash
git clone https://github.com/THEIR-USERNAME/creed.git
```

```bash
cd creed
```

Worked: a `creed` folder with `README.md` inside. **Every later command runs from this folder.**

## Step 2: Connect their watch

Ask which watch they wear, then follow **2a** for Garmin, **2b** for any other watch, or **2c** if they have none.

### 2a: Garmin

1. Open the Garmin Connect key page: https://connect.garmin.com/app/settings/personalApiToken
2. Create a key. **Garmin shows it only once.** Tell them to note the expiry date they choose.
3. Save it on their computer. What they type stays hidden, and it's stored in their user folder, outside the project:

```bash
python tools/garmin_probe.py --save-key
```

Worked: it says the key was saved. (Optional, 5–15 minutes: `python tools/garmin_probe.py` writes a report of what
their account can provide to `probe-output/`.)

### 2b: COROS, Polar, Suunto, Wahoo, Amazfit or another watch (through intervals.icu)

1. Create a free account at https://intervals.icu and connect their watch's app on its **Settings** page. Give it a few
   minutes to bring in their history.
2. On the same Settings page, scroll to **Developer Settings** and find their **API key**. It doesn't expire. They'll
   put it into `.env` in step 3, not into this chat.

Tell them what to expect: workouts with maps and heart rate, sleep length and score, resting heart rate, HRV and steps
all come across. Body Battery, stress, sleep stages and Garmin's training effects only exist with Garmin. Activities
that reached intervals.icu from Strava can't be passed on to other apps, so the watch should connect to intervals.icu
directly. If they wear a Garmin, steer them to 2a: Garmin is limiting what intervals.icu can share with other apps.

### 2c: No watch

Nothing to create. In step 3 they add `CREED_DATA_SOURCE=none` to `.env`, and in step 5 the same in Vercel. Tell them
what they get: the race countdown, food logging with the barcode scanner, training and rest day targets (they mark
each day by hand on the Food screen), trends and reminders. Recovery, sleep, fitness and maps need a watch; they can
add one later by changing `CREED_DATA_SOURCE` and adding its key. Skip `python -m creed.sync` in step 4: there's
nothing to sync.

## Step 3: Create the database

1. On Supabase, create a **new project**. Pick the region nearest them. Save the **database password** in a password
   manager.
2. In the project, click **Connect**, then the **Direct** tab, then **Transaction pooler**. Copy that connection string.
3. In the `creed` folder, copy `.env.example` to a new file called `.env`.
4. In `.env`, set `DATABASE_URL=` to that connection string, with their password put in place of the password
   placeholder. They do this in their editor, not in this chat.

5. **intervals.icu only (2b):** also add `CREED_DATA_SOURCE=intervals` and `INTERVALS_API_KEY=` with their key, then
   check it works. It prints only counts:

```bash
python tools/intervals_check.py
```

Worked: `.env` exists and has a `DATABASE_URL` line (and, for intervals.icu, the check says "The key works").
Remind them never to commit `.env`.

## Step 4: Install and copy their data in

Run these one at a time:

```bash
python -m venv .venv
```

```bash
.venv/Scripts/python -m pip install -e ".[dev]"
```

```bash
.venv/Scripts/python -m creed.db.migrate
```

```bash
.venv/Scripts/python -m creed.sync
```

A sync stops after 150 requests or 240 seconds. If it says **"History is still being copied"**, run the last command
again until it doesn't. Later syncs take seconds.

Worked: each command finishes without an error, and the last sync no longer says "History is still being copied".

## Step 5: Put it online with Vercel

1. On Vercel: **Add New → Project**, import their fork.
2. Choose a **Project Name**. It becomes their address, `https://NAME.vercel.app`, and **passkeys are tied to that
   address for good**, so pick one they'll keep. Leave every other setting alone (`vercel.json` sets them).
   Click **Deploy**. The site loads but can't sign in yet; that's expected.
3. Check the real address under **Domains** on the project page. Vercel may have changed the name if it was taken.
4. Make two long secrets. Run this **twice**; the first result is the **setup secret**, the second the
   **cron secret**. Save both in a password manager:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

5. In the project's main sidebar (not inside Settings), open **Environment Variables**. Add each of these with only
   **Production** ticked, and the **Secret** type for all except `CREED_ORIGIN`:

| Name | Value |
|---|---|
| `DATABASE_URL` | The Supabase Transaction pooler string from step 3 |
| `GARMIN_PERSONAL_API_KEY` | Their Garmin key (2a only) |
| `CREED_DATA_SOURCE` | `intervals` for 2b, `none` for 2c. Leave it out for Garmin. |
| `INTERVALS_API_KEY` | Their intervals.icu API key (2b only) |
| `CREED_ORIGIN` | Their address from step 5.3, starting `https://`, no slash at the end |
| `CREED_SETUP_SECRET` | The setup secret |
| `CRON_SECRET` | The cron secret |

6. Go to **Deployments**, open the menu beside the latest one, choose **Redeploy**. Settings only apply to new
   deployments.
7. Open `https://NAME.vercel.app/api/auth/status`.

Worked: it shows `"signed_in":false`. If it shows an error, `DATABASE_URL` is the usual cause.

If their Supabase database isn't in Mumbai, change `regions` in `vercel.json` to the nearest Vercel region
(https://vercel.com/docs/regions), commit and push.

## Step 6: Install it on their phone

1. On iPhone, open their address in **Safari**, tap **Share**, then **Add to Home Screen**.
2. Open Creed from the home screen, enter the **setup secret**, and create a passkey with Face ID.
3. **Save the recovery code** it shows somewhere safe. It's shown only once.

Worked: they see the Today screen with their data.

## Step 7: Turn on the scheduled sync

1. In their GitHub fork: **Settings → Secrets and variables → Actions → New repository secret**. Add:

| Name | Value |
|---|---|
| `CREED_URL` | Their address, like `https://NAME.vercel.app` |
| `CRON_SECRET` | The same cron secret as in Vercel |

2. GitHub turns schedules off on forks, so open the **Actions** tab and click to enable workflows.
3. Choose **Sync training data**, then **Run workflow**.

Worked: the run finishes with a green tick. From now on Creed syncs every 30 minutes, plus a daily backup from Vercel.

**That's the core setup done.** Congratulate them, then offer the optional steps.

---

## Optional: import their full Garmin history (Garmin only)

Garmin's API only goes back so far. To bring in everything:

1. On Garmin's **Export Your Data** page in their account settings, request their data. Garmin emails a zip link,
   usually within a few days.
2. Put the zip, **unopened**, in a folder called `exports` inside `creed`. Don't upload it anywhere.
3. Run:

```bash
.venv/Scripts/python -m creed.sync.export
```

Worked: a report of days found and how many were new. Running it again changes nothing.

## Optional: notifications

1. Make the key pair once (it writes both keys to `.env` without printing them):

```bash
.venv/Scripts/python tools/make_vapid_keys.py
```

2. Copy `PUSH_VAPID_PRIVATE_KEY` and `PUSH_VAPID_PUBLIC_KEY` from `.env` into Vercel's Environment Variables, then
   redeploy. **Don't make a new pair later**, or phones stop getting notifications until they turn them on again.
3. In the app from the home screen: **Settings** (the gear on Today), turn on **On this phone** under Notifications,
   and pick which ones they want. For food reminders: **Food → Food settings → Remind me to log**.

Notifications go out when the scheduled sync runs, so within about half an hour of the chosen time.

## After setup

- Race date, time zone and heart-rate settings: **Settings**, behind the gear on Today.
- **The Garmin key expires.** Before the date they noted, make a new key, replace `GARMIN_PERSONAL_API_KEY` in Vercel,
  and redeploy. Offer to remind them how.
- After updating their copy of the code, run `.venv/Scripts/python -m creed.db.migrate` again. It only applies what's
  new.

## Troubleshooting

| What they see | What to do |
|---|---|
| `python` not found | Use `python3`, or reinstall Python with "Add to PATH" ticked (Windows). |
| `/api/auth/status` shows an error | Check `DATABASE_URL` in Vercel matches the Transaction pooler string with the right password, then redeploy. |
| Signing in says to set `CREED_ORIGIN` | It's missing in Vercel, or they didn't redeploy after adding it. |
| Tab bar cut off or top of screen blurred (iPhone) | Delete Creed from the home screen and add it again. The passkey is kept, so they just sign in. |
| Sync time on Today turns red | The last sync failed. "Garmin key problem" usually means the key expired; "intervals.icu key problem" means the key was regenerated or mistyped. |
| intervals.icu activities missing | Ones that came to intervals.icu from Strava can't be shared. Connect the watch to intervals.icu directly. |
| The Actions run failed | `CREED_URL` and `CRON_SECRET` in GitHub must match their address and Vercel's `CRON_SECRET`. |
| Something breaks after updating the code | Run `.venv/Scripts/python -m creed.db.migrate`. |
| The 30-minute sync stopped | GitHub pauses schedules after 60 days without repo activity. Re-enable **Sync training data** in Actions; the daily Vercel sync carries on meanwhile. |
| Lost their passkey | Use the recovery code on the sign-in screen, then create a new passkey straight away. |

If you're stuck, point them to the full README (https://github.com/prokp3/creed#readme), or to the "Try Creed" form
on the homepage (https://creed-garmin.vercel.app/welcome/) to ask the creator directly.

## Good to know (share if they ask)

- **Their data stays theirs:** one copy, one person's data, in their own database, with row-level security on every
  table. Nobody else, including the creator, can see it.
- **Creed never asks for their Garmin or intervals.icu password.** It uses the key they created, which they can revoke.
- **Cost:** everything runs on free plans.
- **Unofficial:** Creed isn't affiliated with Garmin or The IRONMAN Group. Garmin's Personal API is meant for an
  individual's own data, and each person running a copy is responsible for following Garmin's terms.
