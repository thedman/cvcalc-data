# Monthly CIA Rate Operations

This document is the operating model for monthly CIA Section 3500 rate updates across the shared data repository, the mobile apps, the marketing site, and subscriber email notifications.

## Objectives

1. Keep `cia_rates.json` current, source-reviewed, and safe for app consumption.
2. Make new monthly rates available to both mobile apps without requiring an app release.
3. Notify CVCalculator rate-update subscribers only after a reviewed monthly rate has been published.
4. Keep the website article aligned with the canonical data source.
5. Make the workflow auditable enough that an operator or AI assistant can identify where a monthly update is stuck.

## Repositories and Responsibilities

| Repository | Responsibility | Current role |
| --- | --- | --- |
| `cvcalc-data` | Canonical public CIA rate data and rate-update automation | Owns `cia_rates.json` and the monthly GitHub Actions workflow |
| `CVCalculator` | iOS app | Fetches `cia_rates.json` at runtime and falls back to bundled rates |
| `CVCalculator_Android` | Android app | Fetches `cia_rates.json` at runtime and falls back to bundled rates |
| `CVCalculator_site` | Marketing and education site | Captures subscriber interest and contains the CIA rates article |
| `shared-lead-registry-worker` | Shared lead intake | Accepts `/lead` submissions and writes them to the shared Google Sheet |

## Canonical Flow

```text
CIA / FTSE / reviewed source
  -> cvcalc-data/cia_rates.json
  -> GitHub raw URL
  -> iOS CIARatesProvider
  -> Android CIARatesProvider
```

The mobile apps should treat `cia_rates.json` as the canonical remote source. Bundled app tables are fallback data only. Updating `cia_rates.json` is therefore production-impacting, even though it is "just JSON."

## Current Implementation

`cvcalc-data/.github/workflows/rate-discovery.yml` runs during the monthly publication window and can also be run manually. It detects when an expected month is missing and opens a discovery issue for human sourcing. `cvcalc-data/.github/workflows/validate-rates.yml` validates PRs that change `cia_rates.json`.

The current workflow does not:

- Add rates automatically.
- Source authoritative CIA / FTSE values by itself.
- Trigger a website article update.
- Trigger subscriber email notifications.

## Target Workflow

The preferred workflow is a reviewed publish model:

```text
Monthly schedule, first business day window
  -> detect missing month in cia_rates.json
  -> collect candidate i1/i2 values from allowed sources
  -> open PR against cvcalc-data
  -> validate JSON shape, ordering, decimal precision, and month uniqueness
  -> human verifies source and approves
  -> merge to main
  -> mobile apps receive rates on next runtime fetch
  -> downstream jobs update site content and send subscriber notification
```

Direct commits to `main` should be reserved for low-risk backfills or emergency corrections where the source has already been independently verified.

## Mobile App Cascade

The mobile cascade is already mostly optimized:

- iOS fetches `https://raw.githubusercontent.com/thedman/cvcalc-data/main/cia_rates.json`.
- Android fetches the same endpoint.
- Both apps retain bundled fallback tables for offline or failed fetch cases.

Operationally, this means a verified merge to `cvcalc-data/main` is enough to make the new rate available to app users. No App Store or Google Play release is required unless the bundled fallback tables need to be refreshed.

Recommended monthly check:

1. Confirm latest `cia_rates.json` month is present on GitHub raw.
2. Launch iOS and Android once on a network connection.
3. Confirm the latest month appears in the rate picker.
4. Confirm offline behavior still falls back to cached or bundled rates.

## Subscriber Notification Workflow

The site subscription forms currently post leads to:

```text
shared-lead-registry-worker POST /lead
  -> Google Apps Script
  -> shared Google Sheet leads tab
```

This is an intake workflow, not a broadcast workflow. The existing Worker supports optional per-lead internal notification email, but it does not currently provide a subscriber broadcast API for monthly CIA rate changes.

Target subscriber workflow:

```text
cvcalc-data main updated with new reviewed month
  -> GitHub Actions downstream notification job
  -> read previous and latest rates
  -> build approved email content
  -> call a protected broadcast endpoint or email service job
  -> send only to subscribed CVCalculator leads
  -> record sent timestamp, status, monthKey, and unsubscribe state
```

Before enabling real sends, the system needs:

- Confirmed consent language on capture forms.
- Subscriber filtering for `product_interest=cvcalculator`.
- Unsubscribe mechanism and suppression list.
- Sender identity, reply-to, and provider selection.
- Dry-run mode that logs intended recipients and rendered content without sending.
- Idempotency by `monthKey` so the same monthly update cannot be sent twice accidentally.

## Website Article Workflow

The CIA rate article should not be hand-maintained independently from `cia_rates.json`.

Target site workflow:

```text
cvcalc-data main updated
  -> downstream job reads cia_rates.json
  -> update current-rate block and history table in CVCalculator_site
  -> open PR or commit using a bot branch
  -> publish site through existing Pages process
```

Until that exists, the manual operating rule is: after each verified rate update, update the article from `cia_rates.json`, not from a separate estimate.

## Monthly Runbook

1. Check latest local and remote `cia_rates.json`.
2. If the expected month is missing, source the authoritative CIA / FTSE values.
3. Add the month only after source review.
4. Validate JSON ordering, uniqueness, and decimal rate format.
5. Merge or commit the reviewed data update.
6. Confirm iOS and Android can fetch the latest month.
7. Update the website article from the canonical JSON.
8. Send or schedule the subscriber email only after unsubscribe, consent, and idempotency checks pass.
9. Record the completed month, source, operator, and downstream status.

## Overdue-Month Escalation

Treat a missing month as an operations exception when:

- the discovery issue has been open for more than five business days;
- the usual reviewed secondary sources have not published the final i1/i2 pair;
- the underlying FTSE input yields are already published; or
- the date is past the normal publication window and `cia_rates.json` still ends at the prior month.

Escalation steps:

1. Keep the discovery issue open and add source-status notes there.
2. Re-check reviewed secondary sources such as CIA/Convyta guidance and Penad.
3. Confirm whether the FTSE input yields for the month are published.
4. If secondary sources remain unavailable, calculate only from authoritative primary inputs and the CIA Section 3500 method.
5. Record every source value, formula step, and rounding step in the PR.
6. Mark the PR as calculated from primary inputs pending secondary-source confirmation.
7. Do not use BoC reference estimates or hard-coded spreads as production data.

## July 2026 Exception

As of July 15, 2026, canonical `origin/main` serves rates through June 2026. July 2026 is overdue and issue `#5` (`CIA rate update needed: 2026-07`) is open.

Discovery did not fail to alert. The July 5, 2026 scheduled run detected `latest_in_data=2026-06`, `expected=2026-07`, and opened the sourcing issue. The workflow did emit a harmless label warning because it referenced a missing `cia-rate` label; the workflow now uses the existing `rates-update` label.

Current source status:

- LSEG has published the June 24, 2026 FTSE Canada index YTM inputs used for the July 2026 calculation.
- Penad lists July 2026 in its 2026 table, but the rate values are blank.
- No reviewed secondary source has been recorded in this repository with the final July 2026 i1/i2 pair.

Do not add July 2026 to `cia_rates.json` until the final pair is either sourced from a reviewed actuarial publication or reproduced transparently from authoritative primary inputs and reviewed in a PR.

## Recommended Engineering Backlog

1. Keep the PR-based reviewed rate workflow as the canonical update path.
2. Reconcile machine-derived historical months against authoritative sources where needed.
3. Add a downstream site-update workflow that opens a PR in `CVCalculator_site`.
4. Design a protected broadcast endpoint or worker job for monthly rate emails.
5. Add subscriber status, unsubscribe, and monthly-send audit columns to the shared lead sheet or a more durable subscriber store.
6. Add an operations status check that reports latest data month, site article month, iOS fetch status, Android fetch status, and subscriber-send status.
