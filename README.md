# Creed

A personal triathlon dashboard built from your own Garmin data, installed on your iPhone's home screen as a web app.

**Status: early development.** The data-availability probe, the Garmin sync, the metrics, the API, the screens and passkey sign-in work on a local computer. Sign-in has been tested with a simulated passkey, not yet on a real iPhone. Notifications, the account-export importer and the full deploy guide will be added here as they are built.

## Set up for development

This needs Python 3.12 or newer. On macOS or Linux, use `.venv/bin/python` in place of `.venv/Scripts/python`.

```bash
python -m venv .venv
```

```bash
.venv/Scripts/python -m pip install -e ".[dev]"
```

Run all the tests. They start their own temporary Postgres, so they need no accounts or network:

```bash
.venv/Scripts/python -m pytest
```

## Sync your Garmin data

1. Save your Garmin key using the steps below.
2. Create a free [Supabase](https://supabase.com) project and copy its **Transaction pooler** connection string.
3. Copy `.env.example` to `.env`, then set `DATABASE_URL` in it.
4. Create the tables:

   ```bash
   .venv/Scripts/python -m creed.db.migrate
   ```
5. Copy your data. A run stops at 150 requests or 240 seconds, and the next run carries on from there:

   ```bash
   .venv/Scripts/python -m creed.sync
   ```

## Run the app on your computer

This needs [Node.js](https://nodejs.org) as well, and a database filled by the steps above. Install the web tools once:

```bash
npm --prefix web install
```

Start the API and leave it running. It listens on this computer only. It keeps a random token in `.dev-token` and saves it as a 24-hour session in the database `DATABASE_URL` points at, so keep that file private:

```bash
.venv/Scripts/python tools/dev_api.py
```

In a second terminal, start the web app, then open http://localhost:5173. Use `localhost` rather than `127.0.0.1`, because passkeys need a domain name:

```bash
npm --prefix web run dev
```

You start signed in. To try the real sign-in screens, sign out in Settings. Restart the API to start signed in again.

Run the web tests with:

```bash
npm --prefix web test
```

## Signing in

Creed signs you in with a passkey, which on an iPhone means Face ID. A passkey isn't a password you choose. Your device creates it and keeps it, and the server only ever holds its public half.

**The first time:**

1. Choose the app's final address and set `CREED_ORIGIN` to it. See "If the address changes" below.
2. Make a setup secret and set `CREED_SETUP_SECRET` to it:

   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

   A real address needs at least 32 characters, because anyone who guesses the secret can add their own passkey and read your data. On `http://localhost`, which only your computer can reach, any length works.
3. Open the app, enter the secret, and create your passkey.
4. Save the recovery code it shows you. You'll only see it once.

**Adding a passkey later:** registration stays closed without the secret. To add one, choose **Add a passkey with the setup secret** on the sign-in screen. To shut registration completely, delete `CREED_SETUP_SECRET` from the server once you're set up, and add it back if you need it.

**Staying signed in:** a session lasts 30 days from the last time you used the app. Settings lists your passkeys and lets you sign out.

**If you lose your passkey:** use your recovery code on the sign-in screen. It works once, signs out every other device and gives you a new code. That session lasts an hour, so create a new passkey straight away, then remove the lost one in Settings. If you lose the code while you can still sign in, replace it in Settings.

**If the address changes:** a passkey is tied for good to the address it was made on. If `CREED_ORIGIN` changes:

- Every passkey stops working, and you're signed out.
- The app on your home screen still points at the old address, so delete it and add it again from the new one.

To get back in, set `CREED_ORIGIN` to the new address, open it, and use your recovery code or the setup secret to create a new passkey. Neither of those is tied to the address. Then remove the old passkey in Settings.

## How the data is stored

- **One deployment, one person.** There are no user accounts in the database.
- **Dates:** sleep and HRV belong to the date you woke up, matching Garmin's `calendarDate`. Timestamps are stored in UTC along with your local offset at the time.
- **Sources:** each row records whether it came from the API, the account export or a manual entry, so those can be added without changing the schema.
- **Nothing is filled in.** A day with no data has no row. Values that fail validation are kept but flagged, and metrics leave them out.
- **Server side only.** Row-level security is on for every table with no policies, and Supabase's public API roles have no access.

## Metrics

The metrics live in `creed/metrics/`, with no web or database code, and every formula is tested against a hand-worked example. Each one reports its formula, inputs, window, confidence and citation, and says so plainly when there isn't enough data rather than guessing. To add a metric, write one module with a `compute(ctx)` function and list it in `creed/metrics/__init__.py`.

Values tagged Computed are this project's own and don't try to match Garmin or Whoop. Whoop's algorithm is proprietary and isn't replicated. Values tagged Garmin are shown unmodified.

To check the metrics against your own history, run this. It prints aggregates of your health data to the screen and saves nothing:

```bash
.venv/Scripts/python tools/backtest.py
```

## Check what your Garmin account can provide

The probe reports which data your account returns and how far back it goes. It needs Python 3.12 or newer and nothing else.

1. Create a key on the [Garmin Connect key page](https://connect.garmin.com/app/settings/personalApiToken). Garmin only shows it once.
2. Save it. Your input stays hidden, and the key is stored in your user folder, outside this project:

   ```bash
   python tools/garmin_probe.py --save-key
   ```
3. Run the probe. It usually takes 5–15 minutes and writes its report to `probe-output/`:

   ```bash
   python tools/garmin_probe.py
   ```

## Never commit

Keep secrets, Garmin tokens, FIT files, personal data and logos out of this repo. `.gitignore` covers the usual locations, including `probe-output/`, whose reports hold aggregates of your health data.

## Unofficial project

Creed is an independent project. It is not affiliated with, endorsed by or sponsored by Garmin or The IRONMAN Group. Garmin, IRONMAN and related names are trademarks of their respective owners.

Each person who deploys Creed uses their own Garmin Personal API key and is responsible for following Garmin's terms. Garmin describes the Personal API as being for an individual's own data, not for commercial applications serving multiple users.

## License

[MIT](LICENSE)
