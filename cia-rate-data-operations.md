# CIA Rate Data Operations

How the monthly CIA / FTSE Russell prescribed commuted-value (CV) interest rates
reach the CVCalculator apps, how they are kept current, and how they are validated.

---

## Canonical data source

`cvcalc-data / cia_rates.json` is the **single runtime source of truth** consumed by
both apps. Bundled tables inside each app are **fallback only** (offline / first launch
before the first fetch).

```
{ "monthKey": "YYYY-MM", "i1": <decimal>, "i2": <decimal> }
```
- `i1` — rate for the first 10 years (e.g. `0.038` = 3.8%)
- `i2` — rate thereafter (e.g. `0.051` = 5.1%)
- Array is ascending by `monthKey`; the **last** element is the latest available month.

---

## Current-state data flow (as inventoried)

| Path | Mechanism | Status |
|---|---|---|
| **iOS runtime** | `CIARatesProvider` fetches `cia_rates.json`, merges with bundle, caches; `InputsTabView` defaults to the latest available month (preserving explicit historical picks) | ✅ Consumes canonical source |
| **iOS fallback** | `CIARateTable.allRates` (bundled, currently through 2026-06) | ✅ Fallback only |
| **Android runtime** | Expected to fetch the same `cia_rates.json` | ⚠️ **Not verified here** (separate repo, not inspected) |
| **Android fallback** | Bundled table, if any | ⚠️ Unknown — confirm in the Android repo |
| **Remote update (old)** | `monthly-rate-reminder.yml` **derived** rates from Bank of Canada bond yields + fixed spreads and **auto-pushed to `main`** | ❌ Replaced — see below |

### Key finding (data integrity)

The previous workflow did **not** source authoritative CIA/FTSE values. It approximated
them from BoC marketable-bond yields plus hardcoded spreads (`+0.60` / `+1.61`) and
committed directly to production with no review. History shows **2026-05 was
machine-derived** by the bot (and Mar/Apr derived by the same method). Only **2026-06**
was sourced from an authoritative reference (Convyta / FTSE Russell). These derived
months should be reconciled against authoritative sources — they may differ from the
published CIA rates.

---

## Target operating model

```
   scheduled discovery (rate-discovery.yml)
        │  detects a due-but-missing month
        ▼
   opens ONE GitHub issue  ──►  human sources authoritative i1/i2 (CIA/FTSE)
                                      │  (BoC estimate shown only as a cross-check)
                                      ▼
                              PR adds the month to cia_rates.json
                                      │
                              Validate CIA rates (validate-rates.yml) gates the PR
                                      │  merge after review
                                      ▼
                        apps fetch the new latest month automatically
```

Principles: **no fabrication into the dataset**, **no unreviewed production writes**,
**runtime freshness without app releases**.

---

## Update process

1. **Discovery** — `rate-discovery.yml` runs on a schedule (days 1–10 monthly, the
   publication window) and on demand. `check_new_month.py` compares the dataset's latest
   month to the expected-available month. If a newer month is due but missing, it opens a
   single issue (deduped by title) asking a human to source the authoritative value. A
   BoC-derived estimate is attached **only as a sanity-check reference**, clearly labelled
   non-authoritative.
2. **Sourcing (human)** — obtain official i1/i2 from CIA / FTSE Russell; record the source
   URL and retrieval date.
3. **PR** — add the record to `cia_rates.json` on a branch, preserving ascending order;
   open a PR.
4. **Validation** — `validate-rates.yml` runs `validate_rates.py` automatically on the PR.
5. **Review & merge** — a human reviews and merges. Apps pick up the new latest month on
   their next fetch.

---

## Validation rules (`validate_rates.py`)

- Top-level is a non-empty JSON array; file parses as valid JSON.
- Each `monthKey` matches `YYYY-MM`.
- `i1` and `i2` are numeric (not boolean).
- **Hard bounds** `[0.0, 0.12]` → error if outside (blocks merge).
- **Typical band** `[0.02, 0.08]` → warning if outside (surfaced for review, not blocking).
- Months strictly ascending; no duplicates.
- Consecutive-month gaps surfaced as warnings.

Exit non-zero on any hard error so CI fails the PR.

---

## App consumption model

| Requirement | iOS | Android |
|---|---|---|
| Default to latest available remote month | ✅ `syncRateToLatestIfNeeded()` | ⚠️ Verify |
| Preserve explicit historical selection | ✅ `hasExplicitRateSelection` | ⚠️ Verify |
| Offline fallback does not override fresher remote | ✅ provider merges, prefers fetched | ⚠️ Verify |

The Android contract should match iOS: fetch `cia_rates.json`, merge with bundle (prefer
remote), default to latest unless the user explicitly chose a month.

---

## Bundled fallback strategy

- Runtime uses the **remote JSON** for freshness — routine monthly availability does **not**
  require an app release.
- Bundled tables are refreshed during normal **release cycles** so offline/first-launch
  users aren't far behind.
- Optional (phase 2): the workflow can open PRs against the iOS and Android repos to
  refresh bundled tables after a new month merges — requires cross-repo tokens; gated.

---

## Notification / alerting policy

Notify (GitHub issue) only when:
- a new rate month is due but missing;
- source validation fails on a PR (CI failure is the signal);
- a data gap is detected;
- a remote update fails.

No "no change" notifications — discovery is silent when nothing is due.

---

## Failure modes

| Failure | Behaviour |
|---|---|
| Authoritative value cannot be sourced | Human stops; do **not** fabricate. Issue stays open. |
| BoC reference endpoint down | Estimate omitted from the issue; sourcing still proceeds. |
| Malformed PR data | `validate-rates.yml` fails; merge blocked. |
| Gap (missed month) | Validator warns; discovery still flags the newest due month. |
| Remote unreachable by app | App falls back to bundled table (older but valid). |

---

## Manual override process

- To backfill or correct a month: edit `cia_rates.json` on a branch, open a PR; validation
  runs automatically; merge after review.
- To force a discovery check: run the **CIA rate discovery** workflow via `workflow_dispatch`.
- `PUBLISH_DAY` env var tunes when a month is considered "expected available".

---

## iOS vs Android responsibilities

- **Shared (this repo):** maintain `cia_rates.json`, the discovery + validation workflows,
  and these rules.
- **iOS:** keep `CIARatesProvider` pointed at the canonical URL; refresh the bundled
  `CIARateTable` at release; preserve default-to-latest + explicit-selection behaviour.
- **Android:** confirm it consumes the same URL with the same default/preserve/fallback
  semantics; refresh its bundled fallback at release. **(Unverified here — action item.)**
