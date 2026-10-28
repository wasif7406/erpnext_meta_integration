# Meta Integration (Frappe app)

Meta (Facebook / Instagram) **ad spend** into ERPNext as an **expense + payable**.
Expense only — no leads, no CRM, no catalogue or creative sync.

```
Meta ad account ──sync──> Meta Campaign / Ad Set / Ad   cached, browsable
                        └> Meta Insight               one row = one ad's spend on one day
                                                          │
                              ANALYTICS (no GL impact) ───┘  ROAS, campaign performance

Card / statement charge ──> Meta Billing ──> Journal Entry        "already paid" (default)
                                              Dr Advertising Expense
                                              Cr card / wallet / owner account

                                         └─> Purchase Invoice      "on credit"
                                              Dr Advertising Expense
                                              Cr Creditors (Facebook)
                                            └─> Payment Entry (only if credit was given)
```

Two recognition modes (`Meta Account.expense_recognition`):

- **Billing (default)** — expense hits the ledger when Facebook charges the card, as a
  Purchase Invoice settled by a Payment Entry. Daily spend is analytics only.
- **Accrual** — daily spend is booked against a payable (Journal Entry per period). Use this
  only if you need strict month-end matching.

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
| `expense_recognition` | `Billing (Purchase Invoice)` (default) or `Accrual (spend)` |
| `expense_start_date` | cutover: spend before this date is already in the ledger and is never booked |
| `booking_mode` | accrual mode only: `Journal Entry` or `Purchase Invoice` |
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

## 5. Recording a charge (billing mode)

**Record billing charge** on the account → date, amount (as charged), currency + exchange
rate if the card is billed in another currency, the statement reference, and **Paid From**
(the card / wallet / owner account the money actually left).

Two shapes, chosen per entry:

| Payment mode | Posting | Extra work |
|---|---|---|
| **Already paid (direct)** — default | `Dr Advertising Expense / Cr Paid From` (Journal Entry) | none: the charge is settled by definition |
| **On credit (Purchase Invoice)** | `Dr Advertising Expense / Cr Creditors` | a Payment Entry when the invoice is really paid |

Card and wallet charges are already paid, so no Payment Entry is needed for them; AP is only
used when Facebook or an agency actually grants terms.

### Monthly control report: `Meta Spend vs Charges`

One row per month (and per Meta account): insight spend, charges posted, difference, draft
entries, and a status pill.

| Status | Meaning |
|---|---|
| OK | charged within 1.00 of spend |
| Spend not charged | charged less than spend → a missing charge, or the last days of the month not billed yet |
| Charged > spend | charged more than spend → overcharge, tax, or a charge from another ad account |
| Charge without spend | a charge in a month with no spend rows (e.g. VAT-only, or wrong account) |
| Draft entries | a `Meta Billing` entry is still unposted |

It reads `Meta Insight` and `Meta Billing` only — it never posts.

**Read the `Cumulative Difference` column, not the monthly `Difference`.** Meta bills on a
threshold / billing cycle, so the last days of a month are normally charged in the next one:
a single month showing `Spend not charged` is expected, and it flips to `OK` once that cycle
clears. The cumulative figure (running total per account) must come back to ~0.00 — that is
the signal that every rupee of spend was actually charged.

Why not from Meta's API: for card-funded accounts Meta exposes **no** invoices, payment
cycles or transactions (`adspaymentcycles`, `transactions`, `invoices` all return HTTP 400 —
verified on this account). The billing evidence is the card charge; `spend` comes from
insights only.

## 5b. Booking a period (accrual mode, optional)

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
| `meta_integration.api.record_billing(account, billing_date, amount, …)` | create a Meta Billing entry from a card charge |
| `meta_integration.api.post_billing_purchase_invoice(billing)` | post the Purchase Invoice for a billing entry |

## 8. Deliberately out of scope

- Leads, forms, CRM, audiences, creatives, catalogues — spend only.
- Pulling Meta invoices/payment cycles: not available for card-funded accounts (see §5).
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
