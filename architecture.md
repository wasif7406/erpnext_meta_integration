# Meta Integration — design

Status: implemented as the `meta_integration` Frappe app (version 0.2.0).
Scope: **read-only analytics + control**. The app never posts to the ledger.

---

## 1. Model

```
Company ──1:N──> Meta Account   (ad account, token, expense account, cutover)
                     │
                     ├── sync ──> Meta Campaign / Ad Set / Ad     cached, browsable
                     │
                     └── sync ──> Meta Insight   (ad × day × spend/impressions/clicks)
                                        │
                      ┌─────────────────┘
                      ▼
        Meta Spend vs Ledger (report)  ── compares Σ spend with the GL movement
                                          on the account's expense account
```

One Meta account per company is the normal case; several are allowed with a single
`is_default`. Nothing is selected for posting any more — there is no posting.

---

## 2. Why the app does not post (the decision, and the evidence)

The first iteration booked daily spend into a payable (and later, billing documents into a
Purchase Invoice). Both were dropped after checking what Meta actually provides:

| Endpoint (live account, v25.0) | Result |
|---|---|
| `act_x/adspaymentcycles`, `act_x/adspaymentcycle` | HTTP 400 |
| `act_x/transactions` | HTTP 400 |
| `act_x/invoices` | HTTP 400 |
| `act_x?fields=funding_source_details` | OK — **card-funded** |
| `act_x/insights?date_preset=maximum` | OK — spend per day |

Meta's billing endpoints exist for **credit-line** accounts; a card-funded account has no
invoice to fetch. The card statement is the billing evidence, and the money has already
left — so the correct entry is a single manual Journal Entry
`Dr Advertising Expense / Cr <card | wallet | owner account>`. Automating it would only
re-implement data entry, and creating a `Creditors` balance would invent a liability that
does not exist.

The app therefore keeps exactly what a human cannot do by hand: pulling daily spend per
campaign / ad set / ad from the API.

---

## 3. Sync

1. `GET /act_x?fields=id,name,currency,account_status` → name + currency.
2. `GET /act_x/campaigns|adsets|ads` (paged) → upsert cached entities; Meta timestamps
   (`2026-09-27T16:29:59+0500`) are normalised to `YYYY-MM-DD HH:MM:SS`.
3. `GET /act_x/insights?level=ad&time_increment=1&time_range={since,until}` → one row per
   ad per day, keyed `<ad_id>-<date>` (unique in the database).

Rules: ad-level only (campaign/ad-set totals are aggregations, so nothing can be double
counted); the window (`sync_days`, default 7) is re-read because Meta restates spend; stubs
are created for ads that no longer exist so their spend stays visible; each run writes a
`Meta Sync Run`.

---

## 4. The report

`Meta Spend vs Ledger` — Script Report, one row per month and account:

- **Meta Spend**: Σ `Meta Insight.spend` × the account's exchange rate.
- **Booked in Ledger**: Σ `debit − credit` on `Meta Account.expense_account` from `GL Entry`
  (cancelled entries excluded, joined on account + company). Any voucher counts — manual
  JE, Purchase Invoice, Expense Claim.
- **Difference / Cumulative Difference**: the monthly figure is noisy by design (Meta bills
  on a threshold/cycle), so the cumulative figure is the tie-out; tolerance 1.00.
- **Status**: `OK`, `Spend not in ledger`, `Ledger > spend`, `Ledger without spend`,
  `Partial month`.
- **Cutover**: `Meta Account.expense_start_date`. Spend before it is excluded and the month
  containing it is flagged `Partial month` instead of being judged.

---

## 5. Failure modes considered

| Risk | Handling |
|---|---|
| Token expired / revoked | `MetaAPIError` → Error Log + run counters; nothing else breaks |
| Meta restates spend | window re-read; unique key makes the upsert idempotent |
| Ad/campaign deleted in Meta | stub record keeps historical spend visible |
| Slow API / many ads | pagination capped (`MAX_PAGES`) with a logged warning |
| Two syncs at once | per-account `filelock`; daily job enqueues one job per account |
| Report compared against the wrong months | cutover date + `Partial month` status |

---

## 6. Out of scope

Posting, billing documents, ROAS dashboards (the data exists — spend, impressions, clicks
per ad/day — but no dashboard is shipped), leads/CRM, creative or catalogue sync.
