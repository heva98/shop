# Shop ERP — backend

Django + DRF backend implementing the kernel/pluggable module architecture
in `../architecture.txt`.

## Apps

Kernel (always installed): `core` (Entity/Store/User/StoreRole/ModuleRegistry),
`catalog` (Product/Category/UnitOfMeasure), `inventory`
(StoreProduct/StockBatch/StockLedger — the append-only ledger every other
app writes through), `sync` (SyncOutbox).

Pluggable (toggled per entity/store via `core.ModuleRegistry` +
`ModuleEnablement`): `receiving`, `enquiry` (Enquiry + unified peer/hub
Transfer), `pos`, `fiscal` (abstract `FiscalDevice` interface + `ManualEFDDriver`),
`payments` (abstract `PaymentProcessor` interface + `CashProcessor`),
`notifications` (abstract `NotificationChannel` + SMS/Email), `pricing`
(prices, bundles, time-limited promotions), `credit` (customer credit:
customers, credit sales, repayments), `analytics`.

## Setup (Windows / PowerShell)

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env   # edit DATABASE_URL to point at Postgres, or leave blank for SQLite
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

If PowerShell refuses to run the activation script (`running scripts is
disabled on this system`), either run
`Set-ExecutionPolicy -Scope Process RemoteSigned` first, or skip
activation and call the venv's Python directly:
`.venv\Scripts\python.exe manage.py runserver`, etc.

Already-installed dependencies: this repo's `.venv` was set up and
verified during scaffolding (`backend/.venv`), so `pip install` above is
only needed again if you delete it or move machines.

### macOS / Linux
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Admin: http://localhost:8000/admin/
API root: http://localhost:8000/api/<app>/ (see each app's `urls.py`) — e.g.
`/api/core/stores/`, `/api/catalog/products/`, `/api/pos/sales/`.

Auth: `POST /api/auth-token/` with `username`/`password` returns a DRF
token; send it as `Authorization: Token <token>` on subsequent requests.
(Session auth also works for the browsable API while logged into `/admin/`.)
`GET /api/core/users/me/` returns the signed-in user plus their
`store_roles` — the one payload a frontend login flow needs.

Demo data: `python manage.py seed_demo` (idempotent) seeds one entity
("Kariakoo General Stores") — 3 branches, 10 products (some perishable,
some not), stock, prices (including per-crate and per-dozen prices), a
running promotion, 3 credit customers, and 4 demo logins (`cashier1` /
`storekeeper1` / `manager1` / `admin1`, all password `shop12345`).
**Dev/demo only** — it refuses to run when `DEBUG=False`, since its fake
shop and logins must never exist in a real deployment.

Tests: `python manage.py test` — 256 tests, pinning down tenant isolation
(a user from one firm can never read or write another firm's data), role
enforcement (a cashier's token can't do an entity_admin's job), and the
stock-integrity guarantees below.

## Onboarding a real shop (what gets pushed to GitHub, and what doesn't)

`db.sqlite3`, `.env`, and `media/` are all gitignored — no actual `User`,
`Entity`/`Store`, or uploaded logo ever belongs in the repo; a fresh
clone's database starts empty regardless. What's safe (and intended) to
commit and share is *reference data that isn't tied to any one firm's
identity* — the starter retail catalog in `catalog/seed_data.py`
(categories, product names, sizes, VAT classes, units of measure).

So a new shop onboarding onto a clone of this repo:

1. `python manage.py migrate`
2. Create your own entity_admin + shop via the Django admin
   (`/admin/` → add a `core.User`, add a `core.Entity` with your
   shop's name/logo, add a `core.StoreRole` linking them as
   `entity_admin`) — or `createsuperuser` and do the same from the app's
   own Admin → Shop profile / Stores / Users screens once logged in.
3. `python manage.py seed_catalog --entity "<your shop name>"` to
   load the starter catalog into *your* entity — reusable, shippable
   reference data, with no demo users or demo shop attached.
   Or load your own lists from Excel/CSV instead (step 4).
4. In the app, Settings → Import from Excel: suppliers, then products
   (with prices), then opening stock per store. Each import has a
   downloadable template, is previewed first, and is all-or-nothing.

`seed_demo` (above) is a separate, dev-only convenience for working on
this codebase locally — never run it against a real deployment's
database.

## Multi-tenancy

Every entity-owned model is scoped two ways, enforced in both directions:

- **Reads**: `core.queryset_scoping.TenantScopedQuerySetMixin` (or
  `OwnerEntityScopedQuerySetMixin` for the nullable-owner analytics models)
  on each viewset filters `get_queryset()` to the requester's own entity,
  and further to the specific stores they hold a `StoreRole` at where the
  model is store-tied. An `entity_admin` role is entity-wide (store=null).
- **Writes**: a queryset filter can't stop a forged foreign id in a
  request body, so every writable entity/store FK is also checked in its
  serializer via `core.serializers.validate_owned_entity` /
  `validate_owned_store` / `validate_accessible_store`.

`catalog` (Product/Category/UnitOfMeasure) is entity-scoped the same
way — each firm keeps its own catalog, never shared across tenants.
`core.ModuleRegistry` is the one deliberate exception: it's the global
catalog of installable module *definitions*, identical for every entity.

## Roles

`core.permissions` mirrors the frontend's own role matrix (`NAV_DEFS` in
`appData.js`) as API permissions, on top of — not instead of — the tenant
scoping above:

- `RoleRequiredForWrite` (`core.permissions.write_roles(*roles)`) requires
  one of `core.Role`'s four values (`cashier` / `storekeeper` /
  `store_manager` / `entity_admin`) for POST/PUT/PATCH/DELETE; GET/HEAD/
  OPTIONS just need authentication, since tenant/store scoping is the real
  read boundary for most apps.
- `RoleRequired` (`core.permissions.roles(*roles)`) gates reads too — used
  only where scoping alone isn't a tight enough boundary, such as
  `notifications`, which is reporting-adjacent.
- `entity_admin` is always included alongside whichever roles a screen's
  nav entry lists — entity_admin is a superset of every other role within
  their own entity, not a separate, narrower slice of it.

| Screen (NAV_DEFS)        | Write-gated viewsets                                                    | Roles |
|---------------------------|---------------------------------------------------------------------|-------|
| Point of sale              | `pos.Sale`                                                          | cashier, storekeeper, store_manager, entity_admin |
| Stock                      | `inventory.StoreProduct`, `StockBatch`                              | cashier, storekeeper, store_manager, entity_admin |
| Receiving                  | `receiving.Supplier`, `ReceivingInvoice`, `ReceivingInvoiceLine`     | storekeeper, store_manager, entity_admin |
| Customers & credit         | `credit.Customer`, `CustomerPayment` (credit limits and voids: managers only) | cashier, storekeeper, store_manager, entity_admin |
| Enquiries & transfers      | `enquiry.Enquiry`, `Transfer`                                       | store_manager, entity_admin |
| Analytics                  | `analytics` query/dimensions/items, `SavedVisualization`; `notifications.NotificationLog` (read-gated) | store_manager, entity_admin |
| Settings                   | `catalog.*`, `pricing.Price`/`Bundle`/`Promotion`, `payments.PaymentMethod`, `core.ModuleRegistry`/`ModuleEnablement`, features, `core.Entity` (update) | entity_admin (promotions: store_manager too) |
| Admin                      | `core.Store`, `User`, `StoreRole`                                   | entity_admin |

`GET /api/core/users/me/` stays reachable by every role regardless of the
table above — it's a GET, and it's how a frontend login flow learns which
role(s) it's dealing with in the first place.

Creating a new `Entity` (onboarding a firm — the tenant root itself) is
stricter still: superuser-only, via `EntityViewSet.perform_create`, layered
under the entity_admin gate above.

## Stock integrity

`inventory.models.StockLedger.record()` is the only sanctioned way any
module moves stock (Sale, Transfer, ReceivingInvoice all go through it).
It locks the batch row (`select_for_update`) and refuses a delta that
would take `qty_on_hand` negative, raising `InsufficientStockError` —
mapped to an HTTP 400 by `config.exceptions.custom_exception_handler` —
rather than ever overselling under concurrent requests.

**Expiry is per product.** `Product.tracks_expiry` marks perishable goods
(food, drinks, cosmetics). Their batches need an expiry date when received,
counted or imported; everything else (hardware, stationery, soap) has
batches with no expiry date and, usually, no batch number either — one
batch per delivery. `inventory.models.sellable_batches()` is the one
definition of "may be sold": in stock and not expired, where no expiry
date means never expires.

FEFO (First-Expired-First-Out) is enforced, not just available:
`inventory.models.allocate_fefo(store, product, qty)` picks the
earliest-expiring *unexpired* batch(es) first and batches that never
expire last (oldest delivery first), splitting across batches if one
isn't enough. Expired stock is never allocated — it can only be written
off. The till sends only `{product, qty, uom?, discount?}`; the batch
comes from FEFO and the price from pricing (a running `Promotion`, else
the regular `Price`), never from the request.

**Units.** Stock is always held in the product's own unit
(`Product.uom`, the smallest unit sold, e.g. Bottle). Every
`UnitOfMeasure.unit_value` counts the same smallest piece, so
`catalog.models.convert_qty()` converts between them (Crate of 24 → 24
bottles). Receiving converts supplier packs into the stock unit and stores
cost per stock unit. A product can also be sold in another unit when it
has a `pricing.Price` row for that unit (`Price.uom`, e.g. a Crate of 24 at
21,000 when a bottle is 1,000). `SaleLine.qty` is what left the batch (stock
unit); `sell_qty`/`sell_uom`/`unit_price` are what the customer bought,
`discount` what was taken off, and `amount` the stored line value after
the discount that every total and report sums.

**Corrections.** Stock never changes outside the ledger.
`inventory.StockAdjustment` (manager-only) writes stock off with a
reason — expired, damaged, lost, stolen, spoiled, internal use — and
`inventory.StockCount` is a blind stock take: counters enter what they
find without seeing the system's figures, a manager reviews the
differences and approves, and each difference becomes a `stock_count`
ledger entry.

## Offline sync

Every syncable model's `id` (a `UUIDField`) can be set by the client on
create, not just read back — `core.serializers.ClientGeneratedIdMixin`
overrides DRF's default (which treats `editable=False` as `read_only`).
This is what lets a till that created a Sale while offline keep that same
id when it finally syncs, so two stores' outboxes can never collide on
merge (architecture.txt §3/§4). Applied to `pos.Sale`/`SaleLine`,
`receiving.ReceivingInvoice`/`ReceivingInvoiceLine`,
`enquiry.Enquiry`/`EnquiryLine`/`Transfer`/`TransferLine`, and
`inventory.StockBatch`. Omitting `id` still works — the model's own
`default=uuid4` fills it in.

**Offline sales.** The till is the browser at the counter, and it keeps
selling without a connection:

- `GET /api/pos/till/?store=` is the till's snapshot: catalog, units, this
  store's prices for today (a running promotion's price, with the regular
  price and the promotion's name), sellable batches, payment methods,
  credit customers with what they owe, the cashier discount limit, and
  the caller's open shift. The frontend keeps it in IndexedDB
  (`frontend/src/offline/till.js`) and searches/prices from it online or not.
- Every sale goes into an IndexedDB outbox first
  (`frontend/src/offline/outbox.js`), then to `POST /api/pos/sales/record/`,
  which opens, prices, allocates and completes the whole sale in one
  transaction under the till's own id. Resending an id already recorded
  returns that sale (200), so retries never double-record.
- `completed_at` and `shift` are the till's: an offline sale lands in the
  shift and at the time it was rung up.
- Prices: a sale sent straight away (`strict`) is refused if the price
  changed, so the cashier re-checks with the customer still there; a sale
  made offline is recorded at the price charged and an
  `offline_sale_price` audit event lists the difference.
- Limits: a sale sent straight away is refused if it breaks the cashier
  discount limit (without a manager's approval) or a customer's credit
  limit; a sale made offline already happened, so it is recorded anyway
  and a `discount_given` audit event says it was not approved. A
  manager's approval login goes with the one request only and is never
  saved on the till, so a discount needing approval needs the connection.
- Stock is re-checked as for any sale. A refused offline sale stays on the
  till as "could not be recorded" until someone fixes the cause (e.g.
  receives the stock) and retries it, or discards it.
- Opening and closing a shift need the connection; closing is blocked
  while the till still has unsent sales for it.
- `frontend/public/sw.js` lets the app open with no connection, and the
  signed-in profile is kept so a reload offline stays signed in.

**Not yet done**: offline receiving, enquiries and stock adjustments
(online only), and `sync.SyncOutbox`, the server-side outbox for a
separately hosted store server, which is still unused.

## Key flows

- **Receiving**: `POST /api/receiving/invoices/` (status starts `draft`) →
  `POST /api/receiving/invoices/<id>/receive/` — creates/tops-up the named
  `StockBatch` and posts a `Transfer In` ledger entry per line. Lines of
  perishable products need an expiry date; batch numbers are optional.
- **Shifts**: `POST /api/pos/shifts/` `{store, opening_float}` opens the
  caller's shift (one open shift per cashier per store; selling requires
  one). `GET /api/pos/shifts/current/?store=` returns it.
  `POST /api/pos/shifts/<id>/close/` `{counted_cash, note}` closes it and
  returns the Z-report (takings by payment method, discounts, credit
  repayments, expected vs counted cash).
- **POS**: `POST /api/pos/sales/` `{store, items: [{product, qty, discount?}]}`
  opens a sale (status `open`, nothing deducted) →
  `POST /api/pos/sales/<id>/complete/` `{payment_method, amount_tendered |
  payment_reference, discount, approver_username, approver_password,
  customer, credit_amount, customer_name}` — applies a discount off the
  whole sale (shared over the lines, so VAT follows), checks it against
  the entity's `cashier_discount_limit` (managers may give any discount;
  a cashier needs a manager's login as approval), puts `credit_amount` on
  the customer's account within their credit limit, checks payment for
  the rest (cash must cover it; mobile money/bank need a reference),
  deducts stock once, gives the sale its per-store receipt number and
  locks it. `fiscal_result.pending_manual` means the store's standalone
  EFD machine issued the receipt: record its number with
  `POST .../record_fiscal/` `{receipt_number}` (duplicates are refused).
  Sales have no PUT/PATCH/DELETE. `POST .../cancel/` discards an
  unfinished cart; `POST .../void/` `{reason, approver_username,
  approver_password}` reverses a completed sale (stock back to the same
  batches; a credit sale stops counting against the customer) — a store
  manager voids directly, anyone else needs a manager's login as approval.
- **Customer credit (madeni)**: `credit.Customer` (entity-wide: a customer
  who buys on credit at one branch can pay at another; `credit_limit`
  null = no limit, 0 = no credit). What a customer owes is never stored —
  it is completed credit sales less payments not voided
  (`credit.models.with_balances`). `/api/credit/customers/` lists them
  with `owing` (`?owing=true` for debtors), `summary/` and
  `<id>/statement/` (every credit sale and payment with the running
  balance). Anyone at the till may register a customer, but a customer
  added by a non-manager starts at a credit limit of 0, and only managers
  change limits. `POST /api/credit/payments/` `{customer, store, amount,
  payment_method, reference, note}` records a repayment — taken by a
  cashier, it belongs to their open shift, and cash repayments count in
  that drawer's expected cash; `.../void/` `{reason}` (managers) reverses
  one.
- **Promotions**: `pricing.Promotion` `{name, product, uom?, store?,
  promo_price, starts_on, ends_on, is_active}`. While one runs, the till
  charges its price (`pricing.models.effective_price`); a store's own
  promotion wins over a firm-wide one. `/api/pricing/promotions/?running=true`
  lists those in force today.
- **Stock take**: `POST /api/inventory/stock-counts/` `{store, products?}`
  → `.../save/` `[{id, counted_qty}]`, `.../found/` for stock the system
  had no batch for → `.../submit/` → (manager) `.../approve/` or
  `.../reopen/`; `.../cancel/` abandons it. One count in progress per store.
- **Write-offs**: `POST /api/inventory/adjustments/`
  `{batch, qty_delta, reason, note}` (negative qty; only `wrong_entry` may
  add); `POST .../write_off_expired/` `{store}` clears every expired batch.
- **Imports**: `GET /api/imports/` lists the kinds and their columns,
  `GET /api/imports/<kind>/template/` gives a CSV template, and
  `POST /api/imports/<kind>/` (multipart `file`, `store`, `commit`) runs
  `products`, `suppliers`, `prices` or `opening_stock` from CSV or .xlsx
  (read with the standard library — no extra dependency). Without
  `commit=true` it's a preview; with errors nothing is saved.
- **Reports**: `GET /api/reports/{dashboard,sales,sales-trend,shifts,stock,expiry,purchases,losses}/`
  — live from the transactional tables, optional `?store=`, `?start=`/`?end=`.
  The sales report includes each sale's discount, credit part and
  customer. Cashiers see only their own sales/shifts; stock valuation and
  purchases need storekeeper or above.
- **Enquiries**: `POST /api/enquiry/enquiries/` `{requesting_store, note,
  lines: [{product, qty_requested}]}`. The server decides where it goes: a
  branch of a hub firm asks the main store; otherwise every store sees it.
  `.../fulfill/` `{from_store, note, lines: [{product, qty}]}` sends the
  stock (all or part) as one transfer; `.../reject/` (main store, hub mode
  only) and `.../cancel/` (the asking store).
- **Transfers** (`enquiry.Transfer.send` and friends):
  `POST /api/enquiry/transfers/` `{from_store, to_store, note, lines:
  [{product, qty} | {batch, qty}]}` picks batches earliest expiry first
  (never expired), deducts the sender and numbers the transfer per firm →
  `.../confirm_receipt/` `{received_qty_by_line, note}` (receiving store
  only, once; less than sent = `discrepancy` and needs a note, more is
  refused) → `.../resolve/` `{resolution: return_to_sender | received_late
  | write_off}` (a write-off is booked as `lost` at the sender, so it shows
  in the losses report). `.../cancel/` `{reason}` (sender, before receipt)
  puts the stock back. Stock leaving a hub firm's main store is billed to
  the branch at cost, for what it received; `.../pay/` `{payment_method,
  reference}` (main store manager) records the payment. No edit or
  delete.
- **Features**: `core/features.py` — Point of sale, Receiving and Sales
  on credit per store; Transfers and Analytics per firm.
  `GET/PATCH /api/core/features/` (entity admin); `me` returns each
  store's values, and the API refuses what is switched off.
- **Analytics (Data Visualizer)**: `GET /api/analytics/dimensions/` lists
  the metrics and dimensions the caller may use; `GET /api/analytics/query/`
  takes DHIS2-style `dimension=dx:sales.net;profit.margin`,
  `dimension=pe:LAST_12_MONTHS`, `filter=ou:FIRM`, `total=pe` and returns
  rows in the DHIS2 /api/analytics shape. Queries read the transactional
  tables directly (no fact table, nothing to refresh), confined to the
  caller's firm and stores. `GET /api/analytics/items/?dimension=product&search=`
  searches long item lists. `/api/analytics/visualizations/` saves layouts
  (shared within the firm; only the creator edits) and `<id>/pin/` pins
  one to the caller's dashboard. Definitions live in
  `analytics/registry.py`; see architecture.txt §6.

## Reporting & notifications

`python manage.py send_daily_summaries` sends the daily sales/purchases
summary per store via `notifications.channels` (Email uses Django's real
`send_mail`, routed through whatever `EMAIL_BACKEND` is configured —
console in dev; SMS logs rather than calling a real gateway, see below).
`deploy/systemd/shop-daily-summary.timer` runs it each evening.

## Not implemented yet (flagged, not skipped)

- Direct fiscal integration. Stores use a standalone EFD machine and the
  cashier types its receipt number in (`fiscal/drivers/manual_efd.py`).
  A TRA VFD driver would be a sibling implementing `FiscalDevice`, chosen
  in `get_fiscal_driver()`.
- Mobile money / bank aggregator integration — payments are recorded with
  the customer's transaction reference, not confirmed with the provider.
- The sync engine's actual store↔cloud transport (outbox table exists;
  the push/pull worker doesn't).
- Customer credit reminders: what customers owe is visible in the app and
  the credit report, but no SMS reminder is sent to the customer yet. It
  would be a `NotificationChannel` message from a scheduled command, like
  the daily summaries.
- Promotions are a fixed offer price per product. "Buy 2 get 1 free",
  percentage-off and mix-and-match deals aren't modelled.
- Branch billing in hub mode is at cost and in full per transfer; a
  mark-up for branches or part payments would need extending
  `Transfer.record_payment`.
- `payments.PaymentMethod` has no `entity` FK — it's global, same as
  `core.ModuleRegistry` — so an entity_admin toggling "Mobile Money"
  active currently affects every firm on the platform, not just their
  own. Fine for a single-firm deployment; would need an entity FK (same
  pattern as `catalog`) before onboarding a second tenant.
- Settings tabs not yet built: network topology and bundle pricing.
  Bundles exist in the API (`pricing.Bundle`) but the till does not sell
  them yet.
