# Scaling Shoppy: production architecture

`architecture.txt` describes *what* the system is (kernel, modules, data
model). This document describes *how it runs* as the number of shops grows:
the target topology, how requests and data move through it, and the order
in which to add infrastructure. Each stage starts only when something
measurable says it's needed.

## 1. Principles

1. **One deployable, many servers.** Shoppy stays a modular monolith (the
   architecture tests in `core/test_architecture.py` enforce the module
   boundaries). Splitting it into microservices would add network failures
   and operational cost without adding capacity a single Postgres can't already give
   a retail ERP for years. When we scale, we run more identical app servers.
2. **Stateless app servers.** Anything shared between requests lives in
   Postgres, Redis or object storage, never in a process or on a local disk.
   Then adding a server is just "start another copy".
3. **The till never depends on the cloud to sell.** Offline-first is the
   real availability guarantee: a cloud outage delays sync but stops no
   sale. That is why the backend can target 99.9% rather than 99.99%.
4. **Postgres is the source of truth and the coordination point.** Locks
   (`select_for_update`), idempotency (client-generated UUIDs), job leases
   and rate limits on SMS codes all live in it. Redis is only an
   accelerator, so losing it costs speed, never correctness.
5. **Every scaling feature is a no-op on one server.** The replica router,
   job leases, Redis cache and throttles are all switched on by
   configuration, so dev, a single VPS and a fleet run the same code.

## 2. Target architecture

```
           Tills (PWA, IndexedDB outbox)       Back-office browsers
                         │  HTTPS                     │
                         ▼                            ▼
              ┌──────────────────────────────────────────────┐
              │  Load balancer / nginx  (TLS, gzip, static,  │
              │  X-Request-ID, /api/health/ready/ probes)    │
              └──────────────┬───────────────────────────────┘
                             │
          ┌──────────────────┼──────────────────┐
          ▼                  ▼                  ▼
     ┌─────────┐        ┌─────────┐        ┌─────────┐
     │ app 1   │        │ app 2   │   …    │ app N   │   gunicorn + Django
     │ (+jobs) │        │ (+jobs) │        │         │   stateless
     └───┬─┬───┘        └───┬─┬───┘        └───┬─┬───┘
         │ │                │ │                │ │
         │ └───────┬────────┴─┼──────┬─────────┘ │
         │         ▼          │      ▼           │
         │   ┌──────────┐     │  ┌──────────────┐│
         │   │  Redis   │     │  │Object storage││  logos, uploads
         │   │ cache,   │     │  │ (S3 / R2)    ││  (stage 2)
         │   │ throttle │     │  └──────────────┘│
         │   └──────────┘     │                  │
         ▼  writes + till reads                  ▼  reports / analytics
   ┌─────────────────┐  streaming replication  ┌─────────────────┐
   │ Postgres primary│ ──────────────────────▶ │ Postgres replica│
   │ (PITR backups)  │                         │ (read-only)     │
   └─────────────────┘                         └─────────────────┘
          ▲
          │ SMS (Beem / Notify Africa), email (SMTP)  ◀── scheduled jobs,
          │                                              one copy at a time
```

## 3. Components

| Component | Role | Scales by | State |
|---|---|---|---|
| Till (React PWA) | Sells offline from a snapshot; queues sales in an IndexedDB outbox; syncs when online | One per store, so it scales with the number of shops for free | Local: catalog, stock, pending sales |
| nginx / load balancer | TLS, static files, request id, health probes, spreading load across app servers | Managed LB or nginx pair | None |
| App server (Django + DRF under gunicorn) | REST API, business rules (services layer), auth | Add servers; `workers ≈ 2 × CPU + 1` each | None (by design) |
| Scheduled jobs | Daily SMS/email summaries, backups | Run by systemd timers on every app server; `core.jobs.single_flight` lets one copy run | Lease row in `core_joblease` |
| Postgres primary | Every write; the till's reads (stock, prices, shifts) | Vertical first (CPU/RAM/IOPS), then partition big tables | Source of truth |
| Postgres replica | Reports and analytics (`core.db_routing.on_replica`) | Add replicas | Copy of the primary |
| Redis | Till catalog cache, API rate-limit counters | One small managed instance | Disposable |
| Object storage | Uploaded files (logos) | Unlimited | Durable |
| SMS / email providers | Codes, daily summaries | Provider side; batched (`SMS_PROVIDER_CHUNK_SIZE`) | Delivery logs in Postgres |

## 4. Data flow

### 4.1 Online sale (strict)
1. The till sends `POST /api/pos/sales/{id}/complete/` with the sale lines.
2. `pos.services.checkout` opens one transaction on the **primary** and
   locks the store row and each stock batch (`select_for_update`), so two
   tills can never sell the same last unit.
3. It writes the sale, its `StockLedger` rows (append-only) and the receipt
   number, then commits.
4. If stock is short, the sale is refused (400, with the reason) and the cashier sees why.

### 4.2 Offline sale (catch-up)
1. The till records the sale in IndexedDB with its own UUID and shows the
   receipt at once.
2. When the till is back online, `syncOutbox` posts pending sales oldest
   first to `POST /api/pos/sales/record/`.
3. The server is **idempotent on the till's UUID**: sending the same sale twice
   returns the first result. Retries are therefore always safe.
4. A sale that happened is never refused for stock. Missing units are
   logged as ledger type `unrecorded` and raise an alert.
5. A 5xx, 401, 408 or **429** response means "keep it and try later". Only a
   other 4xx, such as a business refusal, marks the sale `rejected`, and a rejected sale stays
   on the till until someone deals with it.

### 4.3 Till snapshot (the read-heavy path)
`GET /api/pos/till/` sends `catalog_version` and `sync_state`.
The server answers with only what changed:
- The catalog comes from Redis, keyed by `CatalogRevision`, so one product
  edit invalidates that shop's entry and no other shop's.
- Stock and prices are diffed per bucket (`sync_state`), so an idle till
  polling every minute receives almost nothing.

### 4.4 Reports and analytics
These are `GET` endpoints decorated with `@on_replica`, so their queries run on
the replica, which is usually less than a second behind. A month-long sales
report then never competes with checkout for the primary's locks or I/O.
With no replica configured, they read the primary as before.

### 4.5 Scheduled jobs
systemd timers fire on every app server. Each job takes a database lease
(`core.jobs.single_flight`) with one atomic `UPDATE … WHERE expires_at <=
now()`. One server wins and the others print "skipped". If the winner
crashes, the lease expires and the next tick runs the job again. The jobs
skip work that is already done, such as summaries already sent, so a re-run
is safe.

## 5. API design

The existing API follows these rules; new endpoints must too.

- **REST over DRF, JSON, under `/api/<module>/`.** Module endpoints are
  guarded by the module registry (`core.features.feature_enabled`), so a
  module that is switched off answers 403 rather than 404.
- **Auth:** expiring tokens (`TOKEN_TTL_HOURS`), with session auth for the
  admin. A suspended shop's tokens die on their next use.
- **Tenancy is enforced on the server, never by a client filter.**
  `TenantScopedQuerySetMixin` limits every queryset to the caller's entity
  and stores, and `core/test_tenancy.py` guards it.
- **Idempotent writes from offline clients:** the client generates the
  UUID primary key, and a replay returns the original.
- **Commands as actions:** state changes that aren't plain CRUD are
  `POST /api/pos/sales/{id}/complete/`, `/void/`, `/cancel/`, and so on. Each runs one
  service function in one transaction.
- **Errors:** `config.exceptions.custom_exception_handler` returns a
  translated message for people (`detail`) and field errors for forms.
  A business-rule refusal (`core.errors.DomainError`, such as too little
  stock) is a 400 with its message, never a 500.
- **Pagination:** page-number, 50 per page. Large exports stream.
- **Rate limits:** 1,200 requests a minute per user and 120 per anonymous
  address by default (`THROTTLE_*_RATE`). Sign-in, sign-up and SMS codes
  have stricter limits of their own, stored in the database.
- **Health:** `/api/health/live/` (the process is up), `/api/health/ready/`
  (the database and cache answer) for the load balancer, and `/api/health/`
  (also checks backup freshness) for the uptime monitor.
- **Tracing:** every response carries `X-Request-ID`, which also appears
  in each log line the request wrote.
- **Versioning:** the API and the PWA ship together, so they stay in step.
  The till's offline payload is the one long-lived contract: never remove
  a field from `record_sale` input. Add new fields as optional.

## 6. Database

The full model is in `architecture.txt` §3. The decisions that matter for
scale:

- **Tenant key on every row path.** Each table reaches `entity_id`
  directly or through `store_id`. That keeps the option of sharding by
  entity open without needing it: a single Postgres serves thousands of shops.
- **UUID primary keys** on syncable tables, generated by clients, so offline
  tills and the cloud never collide.
- **An append-only stock ledger.** Stock on hand is the sum of movements,
  cached per batch in `StockBatch.qty_on_hand` and updated in the same
  transaction under a row lock. History is never rewritten.
- **Money is `Decimal`.** It is computed, not stored, where possible: a
  customer's balance is credit sales minus payments.
- **Hot indexes:** sales by `(store, completed_at)` (migration
  `pos/0002`) and the outbox by `(status, created_at)`. Add an index only when
  a slow-query log names it.
- **Growth plan:** `StockLedger`, `Sale` and `SaleLine` grow with every
  sale. At roughly 50M ledger rows, partition them by month (Postgres
  declarative partitioning). The UUID keys and time columns already allow
  it, and old partitions can then be moved to cheaper storage.
- **Job leases:** `core_joblease` has one row per scheduled job.

## 7. Caching strategy

| Layer | What | Key and invalidation | Notes |
|---|---|---|---|
| Till (IndexedDB) | Catalog, stock, prices | `catalog_version` hash and `sync_state` buckets | The biggest cache: most till reads never reach the server |
| HTTP (nginx) | Hashed static assets, `immutable`, 1 year | File hash in the name | The PWA shell is served by its service worker |
| Shared (Redis) | Till catalog JSON per shop | `till-catalog:{entity}:{revision}`; a new revision makes the old entry unreachable, and it expires on its own | No explicit purge, so no stale reads |
| Shared (Redis) | Throttle counters | DRF keys, sliding window | Per process with the in-memory default, exact with Redis |
| Per request | Roles, feature switches | `core.request_cache`, dropped by signals when they change | Removes repeated permission queries |
| Database | Replica for reports | n/a | Stale by under a second; reports only |

Rules: cache only what is **keyed by a version**, so invalidation is a key
change rather than a purge. Never cache stock or prices on the server,
because those reads must be exact under concurrent sales. Losing Redis
makes the system slower, never wrong.

## 8. Scaling stages

| Stage | Topology | Move on when |
|---|---|---|
| **0 — today** | 1 VPS: nginx, gunicorn, Postgres, systemd timers | CPU above 60% at peak, or you need zero-downtime deploys |
| **1 — separate data** | Managed Postgres with PITR backups, managed Redis (`CACHE_URL`), 2+ app servers behind a load balancer probing `/api/health/ready/` | Report queries show up in the primary's slow log, or the primary's CPU stays above 50% |
| **2 — read scale** | Read replica (`DATABASE_REPLICA_URL`); logos and uploads in object storage (`django-storages`, `STORAGES` setting); error tracking (Sentry) | Ledger and sales tables reach tens of millions of rows; SMS runs take minutes |
| **3 — heavy work off the request path** | Partitioned ledger and sales tables; a task queue (Celery or RQ on Redis) for SMS batches, imports and exports | Only if one region's Postgres is no longer enough, which is unlikely for this market |

### Stage 1 checklist (going from one server to two)
1. Move Postgres to a managed instance (or its own box) and point every
   server's `DATABASE_URL` at it.
2. Set `CACHE_URL=redis://…` on every server. Required: otherwise each
   server caches separately and rate limits multiply.
3. Use identical `.env` files (same `SECRET_KEY`, which SMS code hashes
   depend on).
4. Set the load balancer's health check to `/api/health/ready/`. Keep the
   uptime monitor on `/api/health/`.
5. Run the systemd timers on every server. The job leases prevent double
   sends.
6. Move `media/` to shared or object storage before the second server
   serves uploads. Until then, keep uploads pinned to app 1.
7. Backups: rely on the managed database's point-in-time recovery, and
   run `manage.py backup` only where `BACKUP_DIR` is meant to live.
8. Deploy with `migrate` once, then restart the servers one at a time.
   Migrations must stay backwards-compatible for one release (add the
   column, deploy, then drop the old one).

## 9. What's already in place

- Stateless app servers, a shared cache keyed by version, expiring tokens
  and database-backed rate limits for codes and sign-in.
- Offline-first tills with an idempotent outbox and catch-up that never
  loses a sale.
- Row locking for stock and receipt numbers.
- Job leases (`core/jobs.py`, `JobLease`) on the daily summaries and
  backups.
- Liveness and readiness probes, separate from the backup-aware monitor
  check.
- Request ids in responses and logs, passed through by nginx.
- An opt-in read replica for reports and analytics (`core/db_routing.py`).
- An API rate ceiling, which the till treats as "retry later".

Still to do, at the stages above: object storage for uploads, error
tracking, a task queue and table partitioning.
