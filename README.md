# Creed

A personal triathlon dashboard built from your own Garmin data, installed on your iPhone's home screen as a web app.

**Status: early development.** The data-availability probe and the Garmin sync work. The metrics, dashboard, login, notifications and full deploy guide will be added here as they are built.

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

## How the data is stored

- **One deployment, one person.** There are no user accounts in the database.
- **Dates:** sleep and HRV belong to the date you woke up, matching Garmin's `calendarDate`. Timestamps are stored in UTC along with your local offset at the time.
- **Sources:** each row records whether it came from the API, the account export or a manual entry, so those can be added without changing the schema.
- **Nothing is filled in.** A day with no data has no row. Values that fail validation are kept but flagged, and metrics leave them out.
- **Server side only.** Row-level security is on for every table with no policies, and Supabase's public API roles have no access.

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
