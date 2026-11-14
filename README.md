# Creed

**A triathlon dashboard built from your own watch's data:** Garmin directly, or COROS, Polar, Suunto, Wahoo and more through intervals.icu. It installs on your phone like an app, signs you in with Face ID, and counts down to your race.

**Homepage:** https://creed-garmin.vercel.app/welcome/

Creed was built for training towards IRONMAN 70.3 Goa, and the race date is a setting you can change. It's free, open source, and in daily use on a real iPhone.

## Set up your own Creed

Your Creed runs on your own free accounts, so your data stays yours. It takes about an hour, mostly creating accounts. Pick whichever way suits you:

### Option 1: let an AI guide you (easiest)

1. **[Download the AI setup guide](https://creed-garmin.vercel.app/creed-ai-setup-guide.md)** (or open [`web/public/creed-ai-setup-guide.md`](web/public/creed-ai-setup-guide.md) here on GitHub).
2. Upload it to your AI assistant, such as Claude, ChatGPT or Gemini.
3. Say: **"Help me set up Creed using this guide."**

It asks which computer and phone you have, then walks you through one step at a time and checks each one worked. It never needs your keys or passwords: those only ever go into your own terminal, files and accounts.

### Option 2: follow the steps yourself

Jump to [the step-by-step guide](#step-by-step-setup) below.

## What it does

- **Today:** a race-bib countdown to the second, rings for recovery, strain and sleep, your resting heart rate, this week's run, bike and swim, and your fitness trend.
- **In-Depth:** fitness, fatigue and form, recovery, sleep, weekly load and aerobic efficiency over 7 to 180 days. Every number Creed works out has a **"Why this number"** panel with its formula, inputs and source.
- **Activities:** every run, ride and swim with its load, and a **route map** from your watch's GPS.
- **Food:** log meals in a tap or two, save whole meals as presets, **scan barcodes**, and see calories and protein against training day or rest day targets. Works with no signal.
- **Notifications:** your Recovery score each morning, a recap when a workout syncs, a warning when your weekly load jumps, and a Sunday summary.
- **Syncs on its own:** every 30 minutes, plus a daily backup, plus a Sync now button.
- **Honest numbers:** Garmin's values are shown unchanged and tagged Garmin. Creed's own are tagged Computed, and it says "not enough data" rather than guess.

<details>
<summary>More detail on every feature</summary>

- **Today:** a race-bib countdown to the second, rings for recovery, strain and sleep (each hidden until there's enough data), resting heart rate, sleep against what you need, today's and this week's run, bike and swim, Garmin's own numbers, and your fitness trend.
- **In-Depth:** fitness, fatigue and form, recovery and its inputs, sleep, weekly load, Garmin data, aerobic efficiency and data quality, over 7, 30, 90 or 180 days. Every computed number has a "Why this number" panel with its formula, inputs, window, confidence and source.
- **Activities:** every activity with its load, filtered by run, bike or swim. Runs and rides have a route map drawn from your watch's GPS, with gaps left where the watch lost signal.
- **Food:** log meals in a tap or two. Presets log a whole meal with one tap, with an undo. Your library starts with 30 staple foods (typical values) and you add your own, with values typed per 100 g or per serving and units such as pieces, katoris or scoops. Scan a barcode with the camera, read on the phone, and Creed looks it up in [Open Food Facts](https://world.openfoodfacts.org) for you to check and save. Calories and protein rings fill against training day or rest day targets, and Creed decides the day type from your Garmin workouts (a workout length you choose) unless you pick one. Add your own nutrients, see 7 and 30 day trends, get reminders to log when you haven't for a while, and export or import your log as CSV. Logging works with no signal and catches up when you're back online. A food that doesn't list a nutrient counts as unknown, not zero, and totals say so.
- **Syncing:** every 30 minutes on a schedule, once a day as a backup, and whenever you tap the sync time on Today.
- **Notifications:** your Recovery score each morning at a time you pick, a recap when a workout syncs, a warning when your last week's load jumps to 1.5 times your six-week average or more, a Sunday summary of the week (training, load against last week, food, days to race), and warnings when your Garmin key is about to run out or syncing keeps failing. Each has its own switch in Settings.
- **Feels like an app:** Face ID sign-in with passkeys, screen animations, and haptic taps on iPhone through an unofficial workaround that may not work on every iOS version.
- **Honest numbers:** values from Garmin are shown unchanged and tagged Garmin. Creed's own values are tagged Computed, and Creed shows "not enough data" rather than guess. Missing days are never filled in.

</details>

## Step-by-step setup

### What you need

- A Garmin watch that syncs to Garmin Connect, or any watch that syncs to [intervals.icu](https://intervals.icu) (COROS, Polar, Suunto, Wahoo, Amazfit and more). No watch? Creed still works for the countdown and food: see [No watch](#no-watch) below.
- An iPhone (Android should work too, but hasn't been tried)
- Free accounts on [GitHub](https://github.com), [Supabase](https://supabase.com) and [Vercel](https://vercel.com)
- On your computer: [Python](https://www.python.org/downloads/) 3.12 or newer, [Node.js](https://nodejs.org) 22, and [Git](https://git-scm.com)

The commands are for Windows. On macOS or Linux, use `.venv/bin/python` wherever you see `.venv/Scripts/python`.

> **Keep your secrets secret.** You'll make a Garmin or intervals.icu key, a database password, a setup secret, a cron secret and a recovery code. Put them only in your own terminal, your `.env` file, Vercel, GitHub Secrets and a password manager. Never commit `.env`.

### 1. Get the code

Fork this repo on GitHub, then clone your fork and open a terminal in its folder. Run every command from that folder.

### 2. Connect your watch

Creed reads from one of two places. Pick the one your watch already syncs to.

**Garmin:** read directly from Garmin Connect.

1. Create a key on the [Garmin Connect key page](https://connect.garmin.com/app/settings/personalApiToken). Garmin shows it only once. Note the expiry date you choose.
2. Save it. What you type stays hidden, and the key is stored in your user folder, outside this project:

   ```bash
   python tools/garmin_probe.py --save-key
   ```

**COROS, Polar, Suunto, Wahoo, Amazfit and others:** read through [intervals.icu](https://intervals.icu), which is free.

1. Create an intervals.icu account and connect your watch's app on its **Settings** page. Give it a few minutes to bring in your history.
2. On the same page, scroll to **Developer Settings** and copy your **API key**. It doesn't expire.
3. You'll put it in `.env` in the next step, with `CREED_DATA_SOURCE=intervals` and `INTERVALS_API_KEY=` set to your key.

What you get through intervals.icu: workouts with route maps and heart rate, sleep length and score, resting heart rate, HRV and steps. Body Battery, stress, sleep stages and Garmin's training effects are Garmin's own, so they only appear with the Garmin option. Activities that reached intervals.icu from Strava can't be passed on to other apps, so connect your watch to intervals.icu directly.

> **Wear a Garmin? Use the Garmin option.** Garmin is limiting what intervals.icu can pass on to other apps, so Garmin data reached through intervals.icu may stop arriving.

#### No watch

Skip the key. Set `CREED_DATA_SOURCE=none` in `.env` in the next step, and in Vercel in step 5. The race countdown, food logging, targets, trends and reminders all work, and syncing is skipped rather than failing. Mark days as training or rest by hand on the Food screen. To add a watch later, change `CREED_DATA_SOURCE` and add its key.

### 3. Create the database

1. On Supabase, create a new project in the region nearest you. Keep the database password somewhere safe.
2. Choose **Connect**, then the **Direct** tab, then **Transaction pooler**. Copy that connection string and put your password in it.
3. Copy `.env.example` to `.env`, and set `DATABASE_URL` in it to that string.
4. Using intervals.icu? Also set `CREED_DATA_SOURCE=intervals` and `INTERVALS_API_KEY` in `.env`, then check the key works. It prints only counts:

   ```bash
   python tools/intervals_check.py
   ```

### 4. Copy your data in

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

If the sync says **"History is still being copied"**, run it again until it doesn't. Later syncs take a few seconds.

### 5. Put it online with Vercel

1. On Vercel, choose **Add New → Project** and import your fork.
2. Pick a **Project Name**. It sets your address, `https://<name>.vercel.app`, and **passkeys are tied to that address for good**, so choose one you'll keep. Leave the other settings alone and click **Deploy**. It can't sign you in yet; that's expected.
3. Check your address under **Domains** on the project page, in case Vercel changed the name.
4. Run this **twice** to make two secrets. The first is your **setup secret**, the second your **cron secret**. Keep both in a password manager:

   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
5. In the project's main sidebar (not inside **Settings**), open **Environment Variables**. Add each of these with only **Production** selected, and the **Secret** type for all but `CREED_ORIGIN`:

   | Name | Value |
   |---|---|
   | `DATABASE_URL` | Your Supabase Transaction pooler string |
   | `GARMIN_PERSONAL_API_KEY` | Your Garmin key (Garmin only) |
   | `CREED_DATA_SOURCE` | `intervals` for intervals.icu, or `none` with no watch. Leave it out for Garmin. |
   | `INTERVALS_API_KEY` | Your intervals.icu API key (intervals.icu only) |
   | `CREED_ORIGIN` | Your address from step 3, starting with `https://` and with no slash at the end |
   | `CREED_SETUP_SECRET` | Your setup secret |
   | `CRON_SECRET` | Your cron secret |
6. Go to **Deployments**, open the menu beside the latest one, and choose **Redeploy**.
7. Open `https://<name>.vercel.app/api/auth/status`. It should show `"signed_in":false`. If it shows an error, check `DATABASE_URL`.

The server runs in Mumbai (`bom1` in `vercel.json`). If your database is elsewhere, change `regions` to the [Vercel region](https://vercel.com/docs/regions) nearest it.

### 6. Install it on your phone

1. Open your address in Safari, tap **Share**, then **Add to Home Screen**.
2. Open Creed from the home screen, enter your setup secret, and create your passkey with Face ID.
3. Save the recovery code it shows you. You'll only see it once.

### 7. Turn on the scheduled sync

1. In your GitHub fork, go to **Settings → Secrets and variables → Actions** and add two repository secrets:

   | Name | Value |
   |---|---|
   | `CREED_URL` | Your address, like `https://<name>.vercel.app` |
   | `CRON_SECRET` | Your cron secret, the same as in Vercel |
2. GitHub turns schedules off on forks, so open the **Actions** tab and enable workflows.
3. Choose **Sync training data**, then **Run workflow**, to check it works.

**You're done.** Creed now syncs on its own. Change the race date, time zone and heart-rate settings in **Settings**, behind the gear on Today.

### Optional: import your whole Garmin history (Garmin only)

Garmin's API only goes back so far. Request your data from Garmin's **Export Your Data** page in your account settings; Garmin emails a link to a zip within a few days. Put the zip, unopened, in a folder called `exports` in this project (git ignores it), then run:

```bash
.venv/Scripts/python -m creed.sync.export
```

It brings in daily summaries, sleep and overnight HRV, keeps the API's version where both have a day, and changes nothing if you run it again.

### Optional: notifications

1. Make the key pair once. It adds `PUSH_VAPID_PRIVATE_KEY` and `PUSH_VAPID_PUBLIC_KEY` to `.env` without printing them:

   ```bash
   .venv/Scripts/python tools/make_vapid_keys.py
   ```
2. Copy both into Vercel's **Environment Variables** and redeploy. Don't make a new pair later, or phones stop getting notifications until they turn them on again.
3. In the app, go to **Settings** and turn on **On this phone** under Notifications, then pick which ones you want. For food reminders, go to **Food → Food settings → Remind me to log**.

Notifications go out with the scheduled sync, so within about half an hour of the time you pick.

## Troubleshooting

| Problem | Fix |
|---|---|
| `/api/auth/status` shows an error | Check `DATABASE_URL` in Vercel, then redeploy. |
| Signing in says to set `CREED_ORIGIN` | It's missing from Vercel, or you didn't redeploy after adding it. |
| The tab bar is cut off, or the top of the screen is blurred | Delete Creed from the home screen and add it again. Your passkey is kept in iCloud, so you just sign in. |
| The sync time on Today turns red | The last sync failed. "Garmin key problem" usually means the key has expired. "intervals.icu key problem" means the key was regenerated or mistyped. |
| Some intervals.icu activities are missing | Ones that came to intervals.icu from Strava can't be shared with other apps. Connect your watch to intervals.icu directly. |
| The Actions run failed | Check `CREED_URL` and `CRON_SECRET` in GitHub match your address and Vercel's `CRON_SECRET`. |
| Something breaks after you update your copy | Run `.venv/Scripts/python -m creed.db.migrate` again. It only applies what's new. |

## Reference

<details>
<summary>How syncing works</summary>

- **Every 30 minutes:** GitHub Actions asks your app to sync. GitHub can run this late when it's busy, and may occasionally skip one.
- **Once a day:** Vercel does the same, between 5:30 and 6:29 AM India time, as a backup. To suit your time zone, change `crons` in `vercel.json`. It's in UTC, and the free plan allows one run a day, at some point within the hour you choose.
- **Whenever you want:** tap the sync time at the top of Today. It refuses to start a second sync while one is running.
- **If the 30-minute sync stops:** GitHub turns schedules off on public repositories after 60 days with no repository activity. The daily sync carries on. To turn it back on, go to **Actions**, choose **Sync training data**, and enable it.
- **The logs are public.** Anyone can read Actions logs on a public repository, so the workflow prints only whether the sync worked. The reason for a failure is recorded in the app.
- **Your Garmin key expires.** Make a new one before the date you noted and replace `GARMIN_PERSONAL_API_KEY` in Vercel, then redeploy. An intervals.icu key doesn't expire.
- **intervals.icu:** each sync reads the last few days of wellness and activities, then walks back through your history, and fetches each activity's FIT file for its map and heart rate. Its rows are stored with the source `intervals`, beside where Garmin's would go, so every screen works the same way.

</details>

<details>
<summary>Signing in</summary>

Creed signs you in with a passkey, which on an iPhone means Face ID. A passkey isn't a password. Your device creates it and keeps it, and the server only ever holds its public half.

- **Adding a passkey later:** registration stays closed without the setup secret. To add one, choose **Add a passkey with the setup secret** on the sign-in screen. To close registration completely, delete `CREED_SETUP_SECRET` from Vercel once you're set up, and add it back if you need it.
- **Staying signed in:** a session lasts 30 days from the last time you used the app. Settings lists your passkeys and lets you sign out.
- **If you lose your passkey:** use your recovery code on the sign-in screen. It works once, signs out every other device and gives you a new code. That session lasts an hour, so create a new passkey straight away, then remove the lost one in Settings. If you lose the code while you can still sign in, replace it in Settings.
- **If the address changes:** a passkey is tied for good to the address it was made on. Every passkey stops working and you're signed out. Set `CREED_ORIGIN` to the new address, redeploy, then delete the home-screen app and add it again from the new address. Use your recovery code or setup secret to make a new passkey, because neither is tied to the address. Then remove the old passkey in Settings.

</details>

<details>
<summary>How your data is kept</summary>

- **One deployment, one person's Garmin data.** Your copy holds only your Garmin data, in your own database. Only the account that set up the deployment sees it.
- **Food is kept per person.** Every food table records whose row it is. For food, the server switches to a restricted database role, and row-level security policies let it see only the signed-in person's rows. Each query also filters by person, as a second guard.
- **Server side only.** Row-level security is on for every table, and Supabase's public roles have no access. Secrets and keys never reach the browser.
- **Food on your phone.** So logging works with no signal, your food library, recent days and changes not yet sent are kept in the app's own storage on your phone. Signing out deletes them.
- **Barcodes and notifications.** Barcodes are read on your phone, and only the number goes to your Creed, which asks Open Food Facts; they never see who's asking. Notifications are encrypted for your phone, so Apple's push service can't read them. Food reminders never name what you ate. Workout recaps and the weekly summary include your numbers, so set iPhone Settings › Notifications › Show Previews to When Unlocked if others see your lock screen.
- **The homepage's tap count.** The public homepage at `/welcome/` counts taps on its "Try Creed now" button. It's a single total, kept in `app_setting`, with nothing about who tapped, and it's the only number the API shares without a session.
- **Nothing is filled in.** A day with no data has no row. Values that fail validation are kept but flagged, and metrics leave them out.
- **Dates:** sleep and HRV belong to the day you woke up, as on Garmin. Times are stored in UTC along with your local offset.
- **Sources:** each value records whether it came from Garmin's API, intervals.icu, the account export or a manual entry. Values are tagged on screen with where they came from.
- **GPS stays in the file.** Positions are only read from an activity's file when you open its map, and they're never saved anywhere else. [OpenFreeMap](https://openfreemap.org) supplies the map, with no key and no account, so opening one shows them which area you're looking at.

</details>

<details>
<summary>Metrics</summary>

The metrics live in `creed/metrics/`, with no web or database code, and every formula is tested against a worked example. To add one, write a module with a `compute(ctx)` function and list it in `creed/metrics/__init__.py`.

Values tagged Computed are Creed's own and don't try to match Garmin or Whoop. Whoop's method is proprietary and isn't copied.

To check the metrics against your own history, run this. It prints totals and patterns from your health data to the screen, and saves nothing:

```bash
.venv/Scripts/python tools/backtest.py
```

To see what your Garmin account can provide, run this. It takes 5–15 minutes and writes a report to `probe-output/`, which git ignores:

```bash
python tools/garmin_probe.py
```

</details>

<details>
<summary>Working on the code</summary>

Run the tests. They start their own temporary database, so they need no accounts or network:

```bash
.venv/Scripts/python -m pytest
```

```bash
npm --prefix web install
```

```bash
npm --prefix web test
```

To run the app on your computer, start the server in one terminal and leave it running. It listens on your computer only, and starts you signed in through a 24-hour session kept in `.dev-token`, which git ignores:

```bash
.venv/Scripts/python tools/dev_api.py
```

Then start the web app in a second terminal and open http://localhost:5173 (the homepage is at http://localhost:5173/welcome/). Use `localhost`, not `127.0.0.1`, because passkeys need a domain name:

```bash
npm --prefix web run dev
```

The server uses whichever database `DATABASE_URL` points at, so a passkey you make on your computer goes into your real database. It only works on `localhost`, so remove it in Settings afterwards.

The public homepage lives in `web/welcome/` and is built alongside the app; the AI setup guide is `web/public/creed-ai-setup-guide.md`.

</details>

## Roadmap

- **A full Data Quality page.**
- **Themes.**
- **A hosted version for everyone.** Later, I plan to host Creed on my own server so that anyone can create an account and connect their watch without setting anything up: other watches through intervals.icu's sign-in approval, and Garmin once Garmin approves Creed for its Connect Developer Program, because the Personal API this version uses is only for your own data. Creed will never ask for your password. Until then, follow [Set up your own Creed](#set-up-your-own-creed).

## Never commit

Keep secrets, Garmin keys and tokens, FIT files, personal data and logos out of this repo. `.gitignore` covers the usual places, including `.env`, `.dev-token` and `probe-output/`.

## Unofficial project

Creed is an independent project. It is not affiliated with, endorsed by or sponsored by Garmin, intervals.icu or The IRONMAN Group. Garmin, IRONMAN and related names are trademarks of their respective owners.

Each person who runs their own copy uses their own Garmin Personal API key or intervals.icu API key, and is responsible for following Garmin's and intervals.icu's terms. Garmin describes the Personal API as being for an individual's own data, not for commercial applications serving multiple users.

## License

[MIT](LICENSE)
