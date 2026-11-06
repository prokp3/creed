# Creed

A personal triathlon dashboard built from your own Garmin data. It installs on your iPhone's home screen and works like an app, with Face ID sign-in. It was built for training towards IRONMAN 70.3 Goa, and the race date is a setting you can change.

**Status: early development, in daily use.** It runs on Vercel and is used on a real iPhone. Notifications and themes are still to come; see [Roadmap](#roadmap).

## What it does

- **Today:** a race-bib countdown to the second, rings for recovery, strain and sleep (each hidden until there's enough data), resting heart rate, sleep against what you need, today's and this week's run, bike and swim, Garmin's own numbers, and your fitness trend.
- **In-Depth:** fitness, fatigue and form, recovery and its inputs, sleep, weekly load, Garmin data, aerobic efficiency and data quality, over 7, 30, 90 or 180 days. Every computed number has a "Why this number" panel with its formula, inputs, window, confidence and source.
- **Activities:** every activity with its load, filtered by run, bike or swim. Runs and rides have a **route map** drawn from your watch's GPS, with gaps left where the watch lost signal.
- **Syncing:** every 30 minutes on a schedule, once a day as a backup, and whenever you tap the sync time on Today.
- **Feels like an app:** Face ID sign-in with passkeys, screen animations, and haptic taps on iPhone through an unofficial workaround that may not work on every iOS version.
- **Honest numbers:** values from Garmin are shown unchanged and tagged Garmin. Creed's own values are tagged Computed, and Creed shows "not enough data" rather than guess. Missing days are never filled in.

## Run your own Creed

You can run your own copy for free. It takes about an hour, mostly creating accounts. Every command is for Windows; on macOS or Linux, use `.venv/bin/python` in place of `.venv/Scripts/python`.

### What you need

- A Garmin watch that syncs to Garmin Connect
- An iPhone (Android should work too, but hasn't been tried)
- Free accounts on [GitHub](https://github.com), [Supabase](https://supabase.com) and [Vercel](https://vercel.com)
- On your computer: [Python](https://www.python.org/downloads/) 3.12 or newer, [Node.js](https://nodejs.org) 22, and [Git](https://git-scm.com)

### 1. Get your Garmin key

1. Fork this repo on GitHub, then clone your fork and open a terminal in its folder. Run every command from that folder.
2. Create a key on the [Garmin Connect key page](https://connect.garmin.com/app/settings/personalApiToken). Garmin only shows it once. Note the expiry date you choose.
3. Save it. What you type stays hidden, and the key is stored in your user folder, outside this project:

   ```bash
   python tools/garmin_probe.py --save-key
   ```
4. Optionally, see what your account can provide. It takes 5–15 minutes and writes a report to `probe-output/`, which git ignores:

   ```bash
   python tools/garmin_probe.py
   ```

### 2. Create the database

1. On Supabase, create a new project. Pick the region nearest you and keep the database password somewhere safe.
2. Choose **Connect**, then the **Direct** tab, then **Transaction pooler**. Copy that connection string and put your password in it.
3. Copy `.env.example` to `.env`, and set `DATABASE_URL` in it to that string. Never commit `.env`.

### 3. Copy your data in

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

A sync stops after 150 requests or 240 seconds, so the first one may not bring in all your history. Run it again until it stops saying "History is still being copied". Later syncs take a few seconds.

### 4. Put it online with Vercel

1. On Vercel, choose **Add New**, then **Project**, and import your fork.
2. Choose a **Project Name**. It sets your address, `https://<name>.vercel.app`, and passkeys are tied to that address for good, so pick one you'll keep. Leave the other settings alone, because `vercel.json` sets them. Click **Deploy**. The site loads but can't sign you in yet.
3. Check the address under **Domains** on the project page. If the name was taken, Vercel may have changed it.
4. Make two long secrets. Run this twice and keep both in a password manager. The first is your **setup secret**, the second your **cron secret**:

   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
5. In the project's main sidebar, not inside **Settings**, choose **Environment Variables**. Add each of these with only **Production** selected. Use the **Secret** type for all but `CREED_ORIGIN`:

   | Name | Value |
   |---|---|
   | `DATABASE_URL` | Your Supabase Transaction pooler string |
   | `GARMIN_PERSONAL_API_KEY` | Your Garmin key |
   | `CREED_ORIGIN` | Your address from step 3, starting with `https://` and with no slash at the end |
   | `CREED_SETUP_SECRET` | Your setup secret |
   | `CRON_SECRET` | Your cron secret |
6. Go to **Deployments**, open the menu beside the latest one, and choose **Redeploy**. Settings only apply to new deployments.
7. Open `https://<name>.vercel.app/api/auth/status`. It should show `"signed_in":false`. If it shows an error, check `DATABASE_URL`.

`vercel.json` runs the server in Mumbai (`bom1`), next to a Mumbai database. If your database is somewhere else, change `regions` to the [Vercel region](https://vercel.com/docs/regions) nearest it.

### 5. Install it on your iPhone

1. Open your address in Safari, tap **Share**, then **Add to Home Screen**.
2. Open Creed from the home screen, enter your setup secret, and create your passkey with Face ID.
3. Save the recovery code it shows you somewhere safe. You'll only see it once.

### 6. Turn on the scheduled sync

1. In your GitHub repo, go to **Settings**, **Secrets and variables**, **Actions**, and add these repository secrets:

   | Name | Value |
   |---|---|
   | `CREED_URL` | Your address, like `https://<name>.vercel.app` |
   | `CRON_SECRET` | Your cron secret, the same as in Vercel |
2. GitHub turns schedules off on forks, so open the **Actions** tab and enable workflows.
3. Choose **Sync Garmin data**, then **Run workflow**, to check it works.

### 7. Optionally, import your Garmin history

Garmin's API only goes back so far. To bring in everything Garmin holds, request your data from Garmin's **Export Your Data** page in your account settings. Garmin emails you a link to a zip, usually within a few days.

Don't upload the zip anywhere. Put it, unopened, in a folder called `exports` in your copy of this project, which git ignores. Then run:

```bash
.venv/Scripts/python -m creed.sync.export
```

It reads the newest zip in `exports/` and brings in daily summaries, sleep and overnight HRV. Where the API already has a day, the API's version is kept, and running it again changes nothing. It ends with a report of how many days it found and how many were new. Activities come from the API, so it only counts any that are missing.

That's it. From now on, Creed syncs on its own. Change the race date, time zone and heart-rate settings in **Settings**, behind the gear on Today.

## How syncing works

- **Every 30 minutes:** GitHub Actions asks your app to sync. GitHub can run this late when it's busy, and may occasionally skip one.
- **Once a day:** Vercel does the same, between 5:30 and 6:29 AM India time, as a backup. To suit your time zone, change `crons` in `vercel.json`. It's in UTC, and the free plan allows one run a day, at some point within the hour you choose.
- **Whenever you want:** tap the sync time at the top of Today. It refuses to start a second sync while one is running.
- **If the 30-minute sync stops:** GitHub turns schedules off on public repositories after 60 days with no repository activity. The daily sync carries on. To turn it back on, go to **Actions**, choose **Sync Garmin data**, and enable it.
- **The logs are public.** Anyone can read Actions logs on a public repository, so the workflow prints only whether the sync worked. The reason for a failure is recorded in the app.
- **Your Garmin key expires.** Make a new one before the date you noted and replace `GARMIN_PERSONAL_API_KEY` in Vercel, then redeploy.

## Signing in

Creed signs you in with a passkey, which on an iPhone means Face ID. A passkey isn't a password. Your device creates it and keeps it, and the server only ever holds its public half.

- **Adding a passkey later:** registration stays closed without the setup secret. To add one, choose **Add a passkey with the setup secret** on the sign-in screen. To close registration completely, delete `CREED_SETUP_SECRET` from Vercel once you're set up, and add it back if you need it.
- **Staying signed in:** a session lasts 30 days from the last time you used the app. Settings lists your passkeys and lets you sign out.
- **If you lose your passkey:** use your recovery code on the sign-in screen. It works once, signs out every other device and gives you a new code. That session lasts an hour, so create a new passkey straight away, then remove the lost one in Settings. If you lose the code while you can still sign in, replace it in Settings.
- **If the address changes:** a passkey is tied for good to the address it was made on. Every passkey stops working and you're signed out. Set `CREED_ORIGIN` to the new address, redeploy, then delete the home-screen app and add it again from the new address. Use your recovery code or setup secret to make a new passkey, because neither is tied to the address. Then remove the old passkey in Settings.

## Troubleshooting

- **The tab bar is cut off, or the top of the screen is blurred.** You're probably running a home-screen app installed before this was fixed. iOS only reads the status bar setting when the app is added, so delete Creed from the home screen and add it again. Your passkey is kept in iCloud, so you just sign in with Face ID.
- **Signing in says to set `CREED_ORIGIN`.** It's missing from Vercel, or you didn't redeploy after adding it.
- **The sync time on Today turns red.** The last sync failed. "Garmin key problem" usually means the key has expired.
- **The Actions run failed.** Check that `CREED_URL` and `CRON_SECRET` in GitHub match your address and the `CRON_SECRET` in Vercel.

## How your data is kept

- **One deployment, one person.** Your copy holds only your data, in your own database.
- **Server side only.** Row-level security is on for every table with no policies, and Supabase's public roles have no access. Secrets and keys never reach the browser.
- **Nothing is filled in.** A day with no data has no row. Values that fail validation are kept but flagged, and metrics leave them out.
- **Dates:** sleep and HRV belong to the day you woke up, as on Garmin. Times are stored in UTC along with your local offset.
- **Sources:** each value records whether it came from Garmin's API, the account export or a manual entry, so those can be added without changing the database.
- **GPS stays in the file.** Positions are only read from an activity's file when you open its map, and they're never saved anywhere else. [OpenFreeMap](https://openfreemap.org) supplies the map, with no key and no account, so opening one shows them which area you're looking at.

## Metrics

The metrics live in `creed/metrics/`, with no web or database code, and every formula is tested against a worked example. To add one, write a module with a `compute(ctx)` function and list it in `creed/metrics/__init__.py`.

Values tagged Computed are Creed's own and don't try to match Garmin or Whoop. Whoop's method is proprietary and isn't copied.

To check the metrics against your own history, run this. It prints totals and patterns from your health data to the screen, and saves nothing:

```bash
.venv/Scripts/python tools/backtest.py
```

## Working on the code

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

Then start the web app in a second terminal and open http://localhost:5173. Use `localhost`, not `127.0.0.1`, because passkeys need a domain name:

```bash
npm --prefix web run dev
```

The server uses whichever database `DATABASE_URL` points at, so a passkey you make on your computer goes into your real database. It only works on `localhost`, so remove it in Settings afterwards.

## Roadmap

- **Notifications:** "Recovery is ready", "Garmin key expiring soon" and "Sync failed". The settings for them are already there.
- **A full Data Quality page.**
- **Themes.**
- **A hosted version for everyone.** Later, I plan to host Creed on my own server so that anyone can create an account with an ID and password, connect their own Garmin, and use it without setting anything up. Connecting other people's Garmin accounts needs Garmin's approval through its Connect Developer Program, because the Personal API this version uses is only for your own data. Creed will never ask for your Garmin password. Until then, follow [Run your own Creed](#run-your-own-creed).

## Never commit

Keep secrets, Garmin keys and tokens, FIT files, personal data and logos out of this repo. `.gitignore` covers the usual places, including `.env`, `.dev-token` and `probe-output/`.

## Unofficial project

Creed is an independent project. It is not affiliated with, endorsed by or sponsored by Garmin or The IRONMAN Group. Garmin, IRONMAN and related names are trademarks of their respective owners.

Each person who runs their own copy uses their own Garmin Personal API key and is responsible for following Garmin's terms. Garmin describes the Personal API as being for an individual's own data, not for commercial applications serving multiple users.

## License

[MIT](LICENSE)
