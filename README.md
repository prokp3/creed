# Creed

A personal triathlon dashboard built from your own Garmin data, installed on your iPhone's home screen as a web app.

**Status: early development.** Only the data-availability probe works so far. The dashboard, deploy guide and one-command setup will be added here as they are built.

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

Run the tests with:

```bash
python -m unittest discover -s tests
```

## Never commit

Keep secrets, Garmin tokens, FIT files, personal data and logos out of this repo. `.gitignore` covers the usual locations, including `probe-output/`, whose reports hold aggregates of your health data.

## Unofficial project

Creed is an independent project. It is not affiliated with, endorsed by or sponsored by Garmin or The IRONMAN Group. Garmin, IRONMAN and related names are trademarks of their respective owners.

Each person who deploys Creed uses their own Garmin Personal API key and is responsible for following Garmin's terms. Garmin describes the Personal API as being for an individual's own data, not for commercial applications serving multiple users.

## License

[MIT](LICENSE)
