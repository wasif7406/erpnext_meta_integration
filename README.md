# Meta Integration (Frappe app)

Meta (Facebook / Instagram) **ad spend** into ERPNext as an **expense + payable**.
Expense only — no leads, no CRM, no catalogue or creative sync.

```
Meta ad account ──sync──> Meta Campaign / Ad Set / Ad  (cached, browsable)
                        └> Meta Insight              (one row = one ad's spend on one day)
                                   │
                    tick "Report to ERPNext" on the campaign / ad set / ad
                                   │
                          book a period (button)
                                   ▼
             Meta Expense Entry ──> Dr Advertising Expense
                                    Cr Payable (Supplier)      [Journal Entry]
                                 or Purchase Invoice             [optional mode]
```

## Why it looks like this

- **Spend is the ledger.** `Meta Insight` rows are the source of truth: each row is
  booked **at most once** (`expense_entry` link), which is what makes re-running a
  booking a no-op.
- **Ad level only.** Insights are pulled once, at ad level, with `time_increment=1`.
  Campaign / ad set totals are aggregations of the same rows, so selecting a campaign
  and one of its ads can never double-count.
- **Nothing financial is hard-coded.** The expense account, payable account and cost
  centre come from the account mapping; the party is the account's Supplier.

## 1. Install

```bash
cd /path/to/frappe-bench
bench get-app meta_integration /path/to/meta_integration
bench --site <site> install-app meta_integration
```

No fixtures and no custom fields: the app owns its doctypes only, so installing it
never touches existing Sales/Purchase customisations.

## 2. Configure a `Meta Account`

`Meta Integration > Meta Account > New`

| Field | Meaning |
|---|---|
| `account_name` | free label, unique per company |
| `company` | ERPNext company that carries the expense |
| `is_default` | required when a company has more than one enabled account |
| `ad_account_id` | `act_1234…` (the `act_` prefix is added if missing) |
| `access_token` | long-lived / system-user token (Password field) |
| `api_version` | Marketing API version, default `v25.0` |
| `currency` | filled by the sync from the ad account |
| `exchange_rate` | account currency → company currency (required if they differ) |
| `booking_mode` | `Journal Entry` (default) or `Purchase Invoice` |
| `supplier` | party for the payable / supplier of the bill |
| `purchase_item` | service item, only for `Purchase Invoice` mode |
| `enable_sync` | master switch for the daily sync |
| `enable_auto_booking` | book the previous month automatically on the 1st (off by default) |
| `sync_days` | how many days back each sync re-reads (default 7) |

**One account per company is the normal case.** Several are supported (one ad account
each); then exactly one must be flagged default, and booking is always done from the
account form you are on, so there is no ambiguity.

### Mapping table

| Role | Required | Requirement |
|---|---|---|
| Advertising Expense | yes | leaf Expense account (e.g. `Facebook Ads`) |
| Payable | yes | leaf Liability account with `account_type = Payable` |
| Cost Center | no | leaf cost centre; falls back to the company default |

Validation blocks accounts from another company, group accounts, wrong root/account
type, and the same account shared by two companies. Missing roles are warnings; the
booking step refuses to run without them.

## 3. Sync

Daily (`hooks.py`) or **Sync now** on the account:

- `/act_x?fields=…` → account name + currency
- `act_x/campaigns`, `act_x/adsets`, `act_x/ads` → upserted into the cached doctypes
- `act_x/insights?level=ad&time_increment=1&time_range=…` → daily spend per ad

Details that matter:

- The window is `sync_days` (default 7) because Meta **restates** spend for a few days.
- Rows that are already booked are **never restated** — a booked amount must match the
  GL. They are counted as "booked rows kept" in the sync run.
- Ads that no longer exist still come back in insights; a stub `Meta Ad` is created so
  their spend stays visible and bookable.
- Every run writes a `Meta Sync Run` row and a one-line `last_run_result` on the account.

## 4. Selecting what to report

Tick **Report to ERPNext** on any campaign, ad set or ad (the checkbox is editable
straight from the list view):

- campaign ticked → every ad under it is included;
- ad set ticked → every ad in that ad set;
- ad ticked → only that ad.

The most specific tick does not "override" an ancestor — selection is a union, and
because rows are ad-level each ad-day is still counted once.

## 5. Booking a period

**Book expenses…** on the account → pick `from_date` / `to_date` (defaults to the
previous month) and a `posting_date` → the dialog previews unbooked rows, selected rows,
the amount (and the converted amount), and the top campaigns by spend → confirm.

What it creates:

1. `Meta Expense Entry` (period, amounts, accounts, child table of included ad-days),
2. either a **Journal Entry** — `Dr Advertising Expense / Cr Payable` with
   `party_type = Supplier`, or a **Purchase Invoice** (company currency, one service
   item line, `credit_to` = mapped payable),
3. stamps every included `Meta Insight` with the entry name.

Guard rails:

- one **Booked** entry per account + period; a second booking of the same period is
  skipped, and a period whose rows are all stamped finds nothing to do;
- rows are stamped with a conditional `UPDATE … WHERE expense_entry IS NULL`, so
  concurrent runs cannot double-book;
- if a voucher is **cancelled**, run
  `bench --site <site> execute meta_integration.reporting.release_entry --args '["MEXP-2026-00001"]'`
  to un-stamp the rows, then book the period again. (Cancelling a Journal Entry
  reverses the GL but cannot call back into the app, hence the explicit step.)

Amounts: `spend` is in the **ad account currency**; `base_amount = spend × exchange_rate`
is what is posted. If both currencies are equal the rate is irrelevant.

## 6. Scheduler (`hooks.py`)

| Job | When | Function |
|---|---|---|
| Sync all accounts | daily `0 2 * * *` | `tasks.sync_all_accounts` (one enqueued job + filelock per account) |
| Book previous month | monthly `0 4 1 * *` | `tasks.book_previous_month` (only accounts with `enable_auto_booking`) |
| Log pruning | weekly | `tasks.prune_logs` (sync runs older than 180 days) |

## 7. Endpoints

| Method | Purpose |
|---|---|
| `meta_integration.api.sync_now(account=None, company=None, days=None, background=0)` | refresh entities + spend |
| `meta_integration.api.preview_expenses(account, from_date, to_date)` | totals for the dialog, writes nothing |
| `meta_integration.api.book_expenses(account, from_date, to_date, posting_date=None, dry_run=0)` | create entry + voucher |
| `meta_integration.api.book_previous_month(account, posting_date=None)` | convenience wrapper |
| `meta_integration.api.release_entry(entry)` | un-stamp after the voucher was cancelled |

## 8. Deliberately out of scope

- Leads, forms, CRM, audiences, creatives, catalogues — spend only.
- Per-campaign expense account overrides (one expense account per Meta account).
- Automatic FX rates (one manual rate per account; change it before booking a month in
  a different rate environment).
- Consolidated multi-account statements — one entry per account per period.
- Query reports/dashboards. The entity list views plus `Meta Insight` filters cover
  drill-down; a "spend vs booked" report is the obvious next addition.

## 9. Tests

```bash
bench --site <site> run-tests --app meta_integration
```

`tests/test_selection.py` covers the selection precedence, aggregation/rounding, the
insight key and the date/currency helpers — the logic where a mistake would silently
mis-state the expense.
