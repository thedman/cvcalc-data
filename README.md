# CVCalculator CIA Rate Data

# Repository Identity

## Quick Reference

Repository: `cvcalc-data`

Classification: Shared public data and automation support repository

Production: Public `cia_rates.json` consumed by CVCalculator apps

Hosting: GitHub repository data file; no application hosting

Deployment: GitHub Actions monthly workflow updates public CIA rate data

Purpose: Maintain safe public CIA rate data used by CVCalculator rate pickers.

Highest Context Switch Risk: Do not treat this as an app repo or invent/hand-edit rates without verified source context.

Read First: `README.md`, `cia_rates.json`, and `.github/workflows/monthly-rate-reminder.yml`.

## What this repository IS

This is the shared public data repository for CVCalculator CIA rate data.

It stores `cia_rates.json` and safe automation code for updating the public output consumed by app clients.

## What this repository is NOT

- Not the iOS app.
- Not the Android app.
- Not the marketing website.
- Not a private data store.
- Not a place for secrets, signing material, store credentials, or raw scrape artifacts.
- Not a place to change app calculation engines or UI behavior.

## Purpose

The repository gives CVCalculator apps a shared public source of CIA rate data. The primary audience is app maintainers and AI assistants maintaining rate-data operations.

Current maturity: active shared data support repository.

Source of truth: `cia_rates.json` for public app-consumed data; `.github/workflows/monthly-rate-reminder.yml` for update automation.

## Production

- Production artifact: `cia_rates.json`.
- Consumers: CVCalculator iOS and Android apps.
- Public-source posture: repository should contain only public rate data and safe automation.

## Hosting

- Hosting platform: GitHub repository.
- App hosting: none.
- Backend/API: none documented.
- CDN/DNS: not applicable.

## Deployment

- Workflow: `.github/workflows/monthly-rate-reminder.yml`.
- Trigger: monthly schedule and manual workflow dispatch.
- Output: updates `cia_rates.json` when a new month is added.
- Rollback: revert data commit if a published rate update is wrong; no separate rollback runbook documented.
- Verification: review source data, generated month key, rate values, and resulting JSON before relying on updates.

## Architecture

- Data: JSON public rate table.
- Automation: GitHub Actions workflow.
- App integration: apps consume the public JSON as provider-backed rate data; bundled app rates are fallback.
- Key constraint: data accuracy and source traceability matter more than automation convenience.

## Analytics

No analytics, telemetry, crash reporting, advertising, or Search Console configuration is documented in this repository.

## Operational Constraints

- Do not commit secrets, credentials, private local configuration, signing material, store credentials, or unnecessary raw scrape artifacts.
- Do not invent CIA rates.
- If local configuration is needed, use `.env.example` placeholders and keep real values out of Git.
- Treat public app-consumed data changes as production-impacting.

## Common Context Switch Mistakes

- Do not modify app code from this repository.
- Do not treat bundled app rates as the canonical remote source.
- Do not assume workflow automation makes a rate official without source review.
- Do not store private data or secrets here because the output is public app-support data.

## Repository Decision History

Decision: Keep CIA rate data in a shared public repository.

Reason: iOS and Android apps need a common provider-backed source to reduce platform-specific rate drift.

Implication: App repositories should treat this repo as the canonical remote rate-data source and keep bundled rates as fallback only.

Decision: Use a GitHub Actions workflow for monthly data updates.

Reason: Monthly rate maintenance is predictable and benefits from repeatable automation.

Implication: Workflow and data changes must be reviewed as production-support changes, not casual documentation edits.

## AI Agent Guidance

First files to read: `README.md`, `cia_rates.json`, and `.github/workflows/monthly-rate-reminder.yml`.

Safe operations: review data, update documentation, inspect workflow logic, and propose validation checks.

Restricted operations: do not invent rates, commit secrets, change app behavior, alter workflow schedule/push behavior, or modify `cia_rates.json` without explicit rate-update context.

Verification commands: inspect JSON validity and workflow logic. Do not run or trigger GitHub Actions without explicit instruction.

This repository stores public CIA rate data used by the CVCalculator app's CIA rates picker.

## Contents

- `cia_rates.json` is the public output consumed by the app.
- `.github/workflows/monthly-rate-reminder.yml` updates the rate file from public source data on a monthly schedule.

## Data Posture

This repo should contain only public rate data and safe automation code. Do not commit secrets, credentials, private local configuration, signing material, store credentials, or raw scrape artifacts that are not required by the app.

If local configuration is ever needed, use `.env.example` with placeholders and keep real values out of Git.
