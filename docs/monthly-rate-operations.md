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

## Automated Production Transaction

The normal monthly path runs entirely in `rate-discovery.yml`, using the repository `GITHUB_TOKEN` with `contents: write` and `issues: write`. No routine PR, approval, CI authorization, PAT, GitHub App, or manual merge is required. Human action is exception-only.

```text
scheduled discovery -> fetch canonical main -> determine next missing month
  -> deterministic Convyta/Penad extraction -> reviewed-source selection
  -> append candidate -> validate candidate -> fast-forward push to main
  -> fetch main again -> validate and compare exact canonical state
  -> record provenance and close monthly issue -> re-evaluate next month
```

Publication requires every gate to pass:

1. The publication calendar deterministically sets the latest expected month.
2. The target is exactly the month after the latest canonical month, never a later calendar month that skips a dependency.
3. Existing approved-host, guidance-context, column-mapping, duplicate/conflict and numeric/plausibility extraction controls pass.
4. Convyta is preferred; Penad is the approved fallback/corroboration. Both usable sources must agree exactly. Disagreement stops publication.
5. The extracted month equals the target. i1/i2 are numeric and the candidate passes `python3 scripts/validate_rates.py cia_rates.json` before committing.
6. The push is an ordinary fast-forward push; concurrent main changes fail closed. Workflow concurrency serializes production discovery runs.
7. After pushing, fetch origin/main again, run the validator against its data, and require the entire canonical dataset to equal the prior dataset plus precisely the reviewed row. This verifies exact i1/i2, unchanged history and advancement by exactly one month.
8. Only verified publication closes a monthly exception issue. Source URL, retrieval time, extracted context, content hash and corroboration are recorded in commit provenance, workflow summary and issue closure.

The workflow never relies on a second workflow triggered by a `GITHUB_TOKEN` commit. The separate validation workflow remains useful for manual PRs/pushes; production publication validation occurs inside the discovery transaction.

Failures identify HUMAN ACTION REQUIRED, expected blocking month and failure stage in the monthly issue. Exact repeated failures are deduplicated. A source wait produces an explicit failed/stale result, rather than a healthy green run. A completed earlier recovery remains published even when a later month has no reviewed evidence.

Example: with canonical August and calendar October, publish and verify September first; then independently discover October. No reviewed September means stop at September. Reviewed September but unavailable October means September recovery succeeds and the October issue remains open. Never insert October before September. Bank of Canada estimates never enter production.

Installation/setup failures also raise an exception when the checkout and Python runtime remain usable. Infrastructure failures that prevent issue tooling from running remain visible as failed workflow runs and require operator recovery.

## Convyta Reviewed-Source Automation

Convyta is an accepted reviewed source for monthly CIA commuted-value rate guidance.

Preferred evidence path:

```text
Convyta resources page
  -> Convyta-hosted HTML guidance/table
  -> COMMUTED VALUE INTEREST RATES row
  -> Period, First 10 Yrs., Thereafter
  -> validated candidate and verified main publication
```

A Convyta-hosted HTML table or page showing the current month and both commuted-value rates is sufficient reviewed evidence when:

- the page is hosted on `convyta.com`;
- the content clearly identifies CIA commuted-value or CV rates and annuity guidance;
- the current month and both commuted-value rates are present;
- the values map unambiguously to `Period`, `First 10 Yrs.`, and `Thereafter`;
- the row is not stale, duplicated, conflicting, or drawn from annuity-proxy columns.

PDF retrieval is optional corroboration or fallback evidence. A downloadable PDF is not required when the HTML evidence is clear and complete. Do not rely on hard-coded hashed PDF URLs; only use PDF links discovered from reviewed Convyta pages.

When Convyta extraction and source selection pass, automation appends exactly the next canonical month, validates the candidate, commits directly to main, and verifies fetched canonical main in the same workflow.

When extraction fails, automation should leave the sourcing issue open. It should comment only when the status materially changes so the issue remains useful rather than noisy.

## Reviewed-Source Selection

Source priority:

1. Convyta reviewed HTML.
2. Penad reviewed HTML.
3. Manual reviewed-source escalation.

Decision rules:

- If Convyta is available, use Convyta.
- If Convyta is unavailable and Penad has a populated reviewed row, use Penad.
- If both sources are available and agree, use Convyta and record Penad corroboration.
- If both sources are available and disagree, stop and require human review.
- If neither source is available, keep the sourcing issue open.

Penad extraction must use the commuted-value interest-rate page and normalize `Rate` and `Post Period Rate` into `i1` and `i2`. Blank rows, malformed tables, wrong-year sections, duplicate/conflicting rows, and inferred values are not acceptable production evidence.

## Publication Timing

Expected-month detection follows the reviewed-source publication calendar instead of a fixed calendar day.

The workflow determines the last Wednesday of the current month. Beginning on the following business day, it starts checking for the next calendar month's rates. Weekend handling is modeled directly. Statutory holidays are handled conservatively by treating a missing source as a normal no-result condition and continuing scheduled checks.

The workflow checks every six hours around the expected publication window and daily throughout the month. It should continue to no-op safely when the canonical dataset is already current.

## GitHub Actions Permissions

The production workflow requests only `contents: write` for publication and `issues: write` for exception lifecycle management. Repository rules must permit the repository Actions token to push main. A rejected push is a production exception; do not bypass it with another credential or weaken contributor policy. No PR permission or approval setting is required by the new happy path.

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
5. Observe automatic validated publication and post-push verification; intervene only for an explicit exception.
6. Confirm iOS and Android can fetch the latest month.
7. Update the website article from the canonical JSON.
8. Send or schedule the subscriber email only after unsubscribe, consent, and idempotency checks pass.
9. Record the completed month, source, operator, and downstream status.

## August 2026 Acceptance Record

Status as of August 7, 2026:

- Canonical source before update: `cia_rates.json` ended at `2026-07`.
- Expected month: `2026-08`.
- Convyta result: checked first; no clear August row was available to automation.
- Penad result: reviewed HTML row `AUG | 3.90 | 5.30`.
- Normalized data row: `{"monthKey":"2026-08","i1":0.039,"i2":0.053}`.
- Automation created branch `rates/2026-08`.
- Automation updated only `cia_rates.json` and validation passed.
- PR `#8` was opened for review and merged manually.
- Issue `#7` closed automatically from the PR.
- Canonical `main` now ends at `2026-08`.
- iOS runtime confirmed August appears after relaunch.
- Android runtime confirmed August appears after relaunch.
- No app release was required for either production app to receive the canonical JSON update.

Operational note: the August workflow proved source discovery, fallback selection, branch creation, data append, and validation. Bot-created PR creation was initially blocked by repository Actions permissions; the permission was enabled afterward. A future source-available month should confirm whether bot-created PRs also trigger validation automatically.

## September 2026 Control Failure and Remediation

Reviewed September evidence was discovered and PR #10 was created correctly. Bot-created PR validation entered GitHub `action_required` state. Required human authorization was not completed; canonical production remained at August and apps therefore remained stale. Repeated scheduled discovery runs did not remediate production. October processing exposed the unresolved prior-month dependency.

Earlier adapter repairs installed PDF dependencies and corrected PDF link/text handling. Those repairs improved discovery, but did not remove the ineffective production authorization gate.

**Control conclusion:** the routine human authorization/merge gate did not operate reliably and is removed from the normal monthly happy path. Human review is now exception-based rather than mandatory for every monthly publication. The automated production gates above replace it without weakening source quality or fail-closed publication controls.

September recovery was merged on October 6, 2026, through PR #10 at `7e2e44d3e00580ea796116ac6c77971263a0fca9`. Canonical September is i1=0.040, i2=0.054. This recovery preceded installation of the unattended transaction and is not evidence that the new pipeline worked. October must be reassessed from canonical September by the new workflow.

## Monthly Rate Sourcing SLA

Expected publication window:

- A reviewed monthly i1/i2 pair should normally be available during the first week of the valuation month.

Escalation threshold:

- If no reviewed pair is available by the 15th, treat the month as a sourcing exception.
- Keep the discovery issue open and begin active source investigation.

Fallback threshold:

- After escalation, a primary-source calculation may be used only when:
  - all authoritative inputs are documented;
  - the CIA calculation is reproduced transparently;
  - the result is independently reviewed;
  - the change is submitted through the normal PR and validation process.

Prohibited sources:

- Never publish from a Bank of Canada estimate alone.
- Never publish inferred, approximate, or unreviewed values.

Source disagreement rule:

- When reviewed sources disagree, STOP. No source takes automatic precedence. Raise a HUMAN ACTION REQUIRED exception and document the resolution before resuming publication.

## Overdue-Month Escalation

Treat a missing month as an operations exception when:

- the discovery issue has been open for more than five business days;
- the usual reviewed secondary sources have not published the final i1/i2 pair;
- the underlying FTSE input yields are already published; or
- the date is past the normal publication window and `cia_rates.json` still ends at the prior month.

Escalation steps:

1. Keep the discovery issue open and add source-status notes there.
2. Re-check reviewed secondary sources in order:
   - current CIA/Convyta monthly guidance;
   - Penad's commuted-value interest-rate table;
   - other reviewed actuarial or pension-administration publications.
3. Confirm whether the FTSE input yields for the month are published.
4. If secondary sources remain unavailable, calculate only from authoritative primary inputs and the CIA Section 3500 method.
5. Record every source value, formula step, and rounding step in the PR.
6. Mark the PR as calculated from primary inputs pending secondary-source confirmation.
7. Do not use BoC reference estimates or hard-coded spreads as production data.

## July 2026 Exception

As of July 15, 2026, canonical `origin/main` serves rates through June 2026. July 2026 is overdue and issue `#5` (`CIA rate update needed: 2026-07`) is open.

Discovery did not fail to alert. The July 5, 2026 scheduled run detected `latest_in_data=2026-06`, `expected=2026-07`, and opened the sourcing issue. The workflow did emit a harmless label warning because it referenced a missing `cia-rate` label; the workflow now uses the existing `rates-update` label.

Updated source status:

- LSEG has published the June 24, 2026 FTSE Canada index YTM inputs used for the July 2026 calculation.
- Penad lists July 2026 in its 2026 table, but the rate values are blank.
- Convyta Partners' July 6, 2026 `CIA Commuted Value and Group Annuity Proxy Guidance` lists July 2026 as i1=3.7% and i2=5.0%.

Add July 2026 to `cia_rates.json` only through a reviewed PR that cites the Convyta July 6, 2026 guidance and closes issue `#5`.

## Recommended Engineering Backlog

1. Maintain the single-workflow validated publication transaction as the canonical monthly update path.
2. Reconcile machine-derived historical months against authoritative sources where needed.
3. Add a downstream site-update workflow that opens a PR in `CVCalculator_site`.
4. Design a protected broadcast endpoint or worker job for monthly rate emails.
5. Add subscriber status, unsubscribe, and monthly-send audit columns to the shared lead sheet or a more durable subscriber store.
6. Add an operations status check that reports latest data month, site article month, iOS fetch status, Android fetch status, and subscriber-send status.
