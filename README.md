# Meta Integration (read-only)

Mirrors Meta (Facebook / Instagram) ad spend into ERPNext for **analysis and control**.
It never creates a Journal Entry, Purchase Invoice or Payment Entry.

```
Meta ad account ──sync──> Meta Campaign / Ad Set / Ad   browsable, with status/budgets
                        └> Meta Insight                 one row = one ad's spend on one day
                                    │
                     (you book the card charge yourself, as a manual JE)
                                    │
                        Meta Spend vs Ledger report ──> spend vs GL, per month
```

## Why it does not post

Two reasons, both verified against this site's account:

1. Meta exposes **no billing documents** for card-funded ad accounts —
   `adspaymentcycles`, `adspaymentcycle`, `transactions` and `invoices` all return
   HTTP 400. Ads Manager → Billing → Payment activity is a UI feature, not an API.
2. The money leaves your card/wallet at the moment of the charge. The correct posting is
   `Dr Advertising Expense / Cr <card | wallet | owner account>` — a **manual Journal
   Entry** from the statement. There is no supplier to credit and no payment to settle.

So the app does the part a human cannot do by hand (daily spend per campaign/ad/set from
the API) and leaves the ledger to you.

## 1. Install

```bash
cd /path/to/frappe-bench
bench get-app meta_integration /path/to/meta_integration
bench --site <site> install-app meta_integration
```

## 2. Configure a `Meta Account`

| Field | Meaning |
|---|---|
| `account_name`, `company` | label and owning company |
| `is_default` | required if a company has more than one enabled account |
| `ad_account_id` | `act_1234…` (the `act_` prefix is added if missing) |
| `access_token` | system-user / long-lived token (encrypted) |
| `api_version` | Marketing API version, default `v25.0` |
| `currency`, `exchange_rate` | filled by the sync; the rate is only used by the report |
| `expense_account` | the ledger account you book ad spend to |
| `expense_start_date` | "Data Starts On": spend before this is already in the ledger |
| `sync_days` | how many days back each sync re-reads (default 7) |
| `enable_sync` | master switch |

`expense_account` and `expense_start_date` exist only for the report — they are not used to
post anything.

## 3. Sync

Daily, or **Sync now** on the account:

- `act_x?fields=…` → ad account name + currency
- `act_x/campaigns`, `adsets`, `ads` → cached, browsable
- `act_x/insights?level=ad&time_increment=1&time_range=…` → daily spend per ad

Meta restates spend for a few days, so the window is re-read every run; `Meta Insight` rows
are keyed `<ad_id>-<date>` and upserted, so nothing is duplicated. Every run writes a
`Meta Sync Run` row plus a one-line `last_run_result` on the account.

## 4. The control: `Meta Spend vs Ledger`

**Reports → Meta Spend vs Ledger** (filters: dates, company, account)

| Column | Meaning |
|---|---|
| Meta Spend | Σ `Meta Insight` spend for the month, converted to company currency |
| Booked in Ledger | Σ (debit − credit) on the mapped `expense_account` for the month — whatever voucher you used |
| Difference | booked − spend |
| Cumulative Difference | running total per account |
| Status | OK · Spend not in ledger · Ledger > spend · Ledger without spend · Partial month |

How to read it:

- **Ignore the monthly `Difference` on its own.** Meta bills on a threshold/cycle, so a
  month's tail is normally charged next month. The **cumulative** difference must come back
  to ~0.00 (tolerance 1.00) — that is the proof every rupee of spend was booked.
- `Partial month` = the month your `expense_start_date` falls inside; the books only cover
  part of it, so it is not judged.
- Set **From Date** to the first month your manual booking covers; earlier months are
  excluded from the spend side by the cutover date.

## 5. Data model

| Doctype | Purpose |
|---|---|
| `Meta Account` | ad account, token, currency, expense account, cutover, sync settings |
| `Meta Campaign` / `Meta Ad Set` / `Meta Ad` | cached entities (browsable, no reporting flags) |
| `Meta Insight` | the spend table: one row per ad per day, unique key |
| `Meta Sync Run` | per-run counters, pruned after 180 days |

## 6. Scheduler and endpoints

| Job | When |
|---|---|
| `tasks.sync_all_accounts` | daily `0 2 * * *` (one enqueued job + filelock per account) |
| `tasks.prune_logs` | weekly (sync runs older than 180 days) |

| Method | Purpose |
|---|---|
| `meta_integration.api.sync_now(account=None, company=None, days=None, background=0)` | refresh entities + spend |
| `meta_integration.api.health()` | which build is deployed |

## 7. Out of scope (deliberately)

- Posting anything: JEs, invoices, payments, expenses. The ledger is manual.
- Leads, CRM, audiences, creatives, catalogues — spend only.
- Meta invoices/payment cycles — not available from the API for card accounts.
- Per-campaign cost allocation, ROAS — the data is there (`Meta Insight` has spend,
  impressions, clicks per ad/day), but no dashboard is shipped yet.

## 8. Tests

```bash
bench --site <site> run-tests --app meta_integration
```

`tests/test_reconciliation.py` covers the status logic and the cumulative tie-out;
`test_datetime.py` the API timestamp normalisation; `test_window.py` the cutover clamp;
`test_packaging.py` the `patches.txt` guard.
