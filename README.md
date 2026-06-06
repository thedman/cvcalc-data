# CVCalculator CIA Rate Data

This repository stores public CIA rate data used by the CVCalculator app's CIA rates picker.

## Contents

- `cia_rates.json` is the public output consumed by the app.
- `.github/workflows/monthly-rate-reminder.yml` updates the rate file from public source data on a monthly schedule.

## Data Posture

This repo should contain only public rate data and safe automation code. Do not commit secrets, credentials, private local configuration, signing material, store credentials, or raw scrape artifacts that are not required by the app.

If local configuration is ever needed, use `.env.example` with placeholders and keep real values out of Git.

