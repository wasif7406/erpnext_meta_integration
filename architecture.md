# Meta Integration — design

Status: implemented as the `meta_integration` Frappe app in this repository.
Scope: **ad spend only**. The spend Meta reports is turned into an ERPNext expense
and a payable. No leads, no CRM, no catalogue/creative sync.

---

## 1. Model

```
Company ──1:N──> Meta Account        (ad account, token, mapping, booking mode)
                     │
                     ├── sync ──> Meta Campaign ─┐
                     │            Meta Ad Set    ├─ cached, browsable, selectable
                     │            Meta Ad        ┘
                     │
                     ├── sync ──> Meta Insight    (ad × day × spend)
                     │                  │
                     │        tick "Report to ERPNext" on any entity
                     │                  │
                     └── book ──> Meta Expense Entry ──> Journal Entry | Purchase Invoice
                                        │
                                        └── stamps every included Meta Insight
```

Cardinality follows the PostEx app: **one Meta account per company is the normal
case**, several are allowed with exactly one `is_default`. Booking is always scoped to
one account, so a multi-account company never has to pick an account implicitly.

---

## 2. DocTypes

| Doctype | Purpose |
|---|---|
| `Meta Account` (autoname `MEA-####`) | ad account id, token, API version, currency, exchange rate, booking mode, supplier, purchase item, mapping table |
| `Meta Account Mapping` (child) | roles → Advertising Expense / Payable / Cost Center |
| `Meta Campaign`, `Meta Ad Set`, `Meta Ad` | cached entities, `report_to_erpnext` checkbox, parent links, budgets, status |
| `Meta Insight` (autoname `<ad_id>-<date>`) | the spend ledger: one row per ad per day, `expense_entry` link, unique key |
| `Meta Expense Entry` (autoname `MEXP-YYYY-#####`) | one booked period: dates, amounts, accounts, voucher links, child table of included ad-days |
| `Meta Expense Entry Insight` (child) | audit trail of what was included |
| `Meta Sync Run` | per-run counters and one-line summary, pruned after 180 days |

`Meta Insight.insight_key` is unique at the database level, so a re-sync of the same day
can never create a duplicate row.

---

## 3. Data flow

### 3.1 Sync (daily or manual)

1. `GET /act_x?fields=name,currency,account_status…` → account name + currency.
2. `GET /act_x/campaigns|adsets|ads` (paged) → upsert cached entities.
3. `GET /act_x/insights?level=ad&time_increment=1&time_range={since,until}` → daily
   spend per ad.

Rules:

- Only one insights call chain per account (ad level). Campaign and ad set totals are
  aggregations, never separate rows — so no double counting by construction.
- Meta restates spend for several days, so the window (`sync_days`, default 7) is
  re-read. A row that is already booked is **not** restated; it is only timestamped.
- An insight referencing an ad/campaign we do not cache creates a stub record, so
  historical spend of deleted ads stays visible.

### 3.2 Selection

`report_to_erpnext` on a campaign, ad set or ad. Selection is inherited downwards and
unioned: campaign → all its ads, ad set → its ads, ad → that ad only. Because rows are
ad-level, overlapping selections still yield each ad-day once.

### 3.3 Booking

`reporting.book_expenses(account, from_date, to_date, posting_date=None, dry_run=False)`

1. refuse if a `Booked` entry already exists for the same account + period;
2. read unbooked, selected insights in the period;
3. create the `Meta Expense Entry` (draft) with the child audit rows;
4. post the voucher:
   - **Journal Entry** (default): `Dr Advertising Expense` / `Cr Payable`
     (`party_type = Supplier`), cost centre on both lines;
   - **Purchase Invoice**: company currency, one service-item line at the converted
     amount, `credit_to` = mapped payable account;
5. stamp every included insight with the entry name (conditional update);
6. mark the entry `Booked` and store the voucher link.

If the voucher posting fails, the entry is marked `Failed` with the error in remarks and
the insights stay unbooked, so the next attempt can retry.

---

## 4. Accounting

```
Booking (both modes)      Dr  Advertising Expense      (mapped, leaf Expense)
                          Cr  Payable                  (mapped, Payable, party = Supplier)
```

The payable is a **real AP balance**: it appears in Accounts Payable by supplier because
the credit line carries `party_type = Supplier` (Journal Entry) or is a submitted
Purchase Invoice. Paying Meta later is an ordinary Payment Entry against that supplier;
this app deliberately does not model the payment side.

Currency: spend is in the ad account currency (`Meta Account.currency`, filled by the
sync). `exchange_rate` converts to the company currency for the voucher. The entry keeps
both `total_spend` (account currency) and `base_amount` (company currency).

---

## 5. Idempotency & failure handling

| Risk | Mitigation |
|---|---|
| Same day re-synced twice | unique `insight_key`; update-in-place for unbooked rows |
| Booked amount restated by Meta | booked rows are skipped during sync |
| Booking the same period twice | pre-check for a `Booked` entry per account + period |
| Two booking runs racing | per-account `filelock` + conditional `UPDATE … WHERE expense_entry IS NULL` |
| Voucher posted, stamping failed | entry exists as `Booked` with the voucher; the period is blocked from re-booking |
| Voucher cancelled later | explicit `release_entry()` un-stamps the rows, then re-book |
| Meta API error / bad token | `MetaAPIError` → Error Log + run counters, never a partial posting |

---

## 5b. Recognition: billing vs accrual

The first version booked daily spend to a payable. That is not how ad spend actually
settles, and it doubles the ledger's work: Meta's API exposes **no** billing documents for
card-funded accounts (`adspaymentcycles`, `adspaymentcycle`, `transactions`, `invoices` all
return HTTP 400), so there is nothing to reconcile a daily accrual against except the card
statement itself.

Adopted model (`Meta Account.expense_recognition`):

| Mode | Expense recognised | Document | Settlement |
|---|---|---|---|
| **Billing** (default) | when the card is charged | `Meta Billing` → Purchase Invoice (`Dr Advertising Expense / Cr Creditors`) | Payment Entry from the bank/wallet feed |
| Accrual | as the spend happens | `Meta Expense Entry` → Journal Entry | Payment Entry when the payout/settlement lands |

`Meta Insight` stays in both modes and is analytics-only in billing mode.

The control that closes the loop is `Meta Spend vs Charges` (Script Report): per month and
account, Σ insight spend (converted to company currency) vs Σ posted billing charges, with a
status — `OK`, `Spend not charged`, `Charged > spend`, `Charge without spend`, `Draft entries`.
It reads data only; the ledger is never touched. Tolerable difference: 1.00. The accrual path is
kept because it is useful for agencies or credit-line ad accounts where month-end matching
matters, and because the same selection logic feeds the ROAS view.

## 6. Decisions

1. **One `Meta Insight` row per ad per day** instead of storing campaign/adset totals —
   removes double counting, gives drill-down, and makes booking auditable.
2. **Expense + payable at booking**, not per day: one voucher per account per period
   keeps the GL readable and matches how the ad invoice arrives.
3. **Journal Entry is the default** booking mode (no item needed, mirrors how the
   merchant already books ad spend); Purchase Invoice is available for shops that want
   supplier-document ageing.
4. **One exchange rate per account**, applied to the period total. Automatic FX would
   need a rate table and a policy decision; deferred.
5. **Manual selection** of campaigns/ad sets/ads; no "book everything" default, because
   a Meta ad account often contains test or agency campaigns.
6. **No payment/payout modelling** — the payable is created; settling it is normal
   ERPNext AP.
