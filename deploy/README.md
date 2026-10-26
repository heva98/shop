# Deploying to shop.example.com

Assumes a fresh Ubuntu/Debian VPS or similar Linux host, with the repo
checked out at `/opt/shop`. Adjust paths/user names below if different
— they must match `nginx/shop.example.com.conf` and
`systemd/shop-gunicorn.service`.

## 0. Get a server

Any Linux VPS works — DigitalOcean, Hetzner, Linode/Akamai, or a local
Tanzanian host. For this app's size, 1 vCPU / 1–2 GB RAM is plenty;
go with 2 GB if you'll run Postgres on the same box. Pick Ubuntu 22.04 or
24.04 LTS. You'll come out of this step with:

- a public IP address for the server
- root (or sudo) SSH access to it

Basic first-login hardening (skip if your provider already does this):

```bash
# as root, right after first login
adduser deploy && usermod -aG sudo deploy   # a human sudo user — don't operate as root day to day
ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw enable
```

From here on, do everything as that sudo user (`ssh deploy@<server IP>`),
prefixing with `sudo` where shown.

## 1. DNS

`shop.example.com` stands for your shop's own domain throughout this
guide and in `nginx/shop.example.com.conf` — replace it everywhere
(including the config file's name). Whoever administers DNS for the domain
(you, your registrar through TZNIC, or your IT provider) adds one record
pointing at the server's public IP from step 0:

```
shop.example.com.  A  <server IP>
```

(If DNS is hosted through a provider's dashboard — e.g. Cloudflare — add
the same `A` record there: type `A`, name `shop` (or `@` for the bare
domain), value `<server IP>`.)

Wait for it to resolve before continuing:

```bash
dig shop.example.com +short   # should print the server's IP
```

This can take anywhere from a few minutes to a few hours depending on the
zone's TTL. Don't skip ahead to step 5's certbot command until this
resolves — Let's Encrypt validates over HTTP, so it fails if the record
isn't live yet.

## 2. System packages

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip nginx postgresql certbot python3-certbot-nginx nodejs npm
sudo useradd --system --home /opt/shop --shell /usr/sbin/nologin shop
```

(Skip `postgresql` if staying on SQLite for now — fine for a small single
school, but Postgres is the stack `architecture.txt` assumes.)

## 3. Get the code and build it

```bash
sudo git clone <your repo url> /opt/shop
cd /opt/shop/backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

cp .env.example .env
# Edit .env: SECRET_KEY (generate one, see the comment in .env.example),
# DEBUG=False, ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS, CORS_ALLOWED_ORIGINS
# all set to shop.example.com, and DATABASE_URL if using Postgres.
chmod 600 .env

.venv/bin/python manage.py migrate
.venv/bin/python manage.py collectstatic --noinput
.venv/bin/python manage.py createsuperuser

cd /opt/shop/frontend
npm ci
npm run build

sudo chown -R shop:shop /opt/shop
```

Nothing above creates a shop, a logo, or any non-superuser login — a
fresh clone's database is always empty of those (`db.sqlite3`, `.env`,
and `media/` are gitignored; the repo only ever ships *code*). After this
step, log into `/admin/` as the superuser you just created and:

1. Add a `core.Entity` — the shop's own name (and logo, once
   logged into the real app's Admin → Shop profile screen).
2. Add a `core.User` for the actual first admin, and a `core.StoreRole`
   linking them to that Entity as `entity_admin`.
3. Optionally seed the standard drug/medicine catalog for them — this
   *is* meant to be shared/reusable, since it's reference data, not this
   firm's identity:
   ```bash
   .venv/bin/python manage.py seed_catalog --entity "<their shop name>"
   ```

Never run `manage.py seed_demo` here — it's dev/demo-only and refuses to
run with `DEBUG=False` anyway, since it would create a fake "Kariakoo
General Stores" entity and fake logins with a published password.

## 4. gunicorn (systemd)

```bash
sudo cp /opt/shop/deploy/systemd/shop-gunicorn.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now shop-gunicorn
sudo systemctl status shop-gunicorn   # should be "active (running)"
```

## 5. nginx + HTTPS

```bash
sudo mkdir -p /var/www/certbot
sudo cp /opt/shop/deploy/nginx/shop.example.com.conf /etc/nginx/sites-available/
sudo ln -s /etc/nginx/sites-available/shop.example.com.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

sudo certbot certonly --nginx -d shop.example.com
sudo systemctl reload nginx
```

certbot installs a renewal timer automatically (`systemctl list-timers |
grep certbot`) — nothing further to do for renewals.

Once HTTPS works, switch on Django's HTTPS settings (they default to off)
by adding to `/opt/shop/backend/.env`, then restart gunicorn:

```bash
SECURE_SSL_REDIRECT=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
```

```bash
sudo systemctl restart shop-gunicorn
```

## 6. Verify

- `https://shop.example.com/admin/` — Django admin loads, login works.
- `https://shop.example.com/api/core/stores/` — returns `401` (expected,
  unauthenticated) rather than a connection error or 502.
- `https://shop.example.com/` — the built frontend loads.
- As an entity_admin: Admin → Shop profile → upload a logo, confirm it
  shows up at `https://shop.example.com/media/entity_logos/...` and in
  the app header.

User-uploaded files (currently just each firm's logo) live in
`backend/media/` — unlike `staticfiles/`, this is real data, not a build
artifact, so include it in whatever backs up the database.

## 7. Backups, alerts, monitoring, SMS

Do this before the shop trades a single day on the system.

### Backups (nightly, checked, kept off the server)

```bash
sudo mkdir -p /var/backups/shop && sudo chown shop:shop /var/backups/shop
sudo apt install -y postgresql-client     # pg_dump / pg_restore, if using Postgres
```

Add to `backend/.env`:

```bash
BACKUP_DIR=/var/backups/shop
BACKUP_KEEP=14            # nightly backups to keep
```

Try it once by hand, then switch on the nightly timer (02:00):

```bash
cd /opt/shop/backend && sudo -u shop .venv/bin/python manage.py backup
sudo cp /opt/shop/deploy/systemd/shop-backup.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now shop-backup.timer
systemctl list-timers | grep shop
```

Each backup is read back and checked before older ones are deleted; a
failure emails `ADMINS` (below) and makes `/api/health/` report `stale`.

**Off-site copy.** A backup on the same server dies with it (disk failure,
hacked or cancelled VPS). Copy them somewhere else every night — e.g. with
[rclone](https://rclone.org) to Google Drive, Backblaze B2 or another server:

```bash
sudo apt install -y rclone
sudo -u shop rclone config          # create a remote called "offsite"
```

then uncomment the `ExecStartPost=` line in
`/etc/systemd/system/shop-backup.service` and `sudo systemctl daemon-reload`.

**Restoring.** Practise this on a spare machine before you need it:

```bash
sudo systemctl stop shop-gunicorn
cd /opt/shop/backend
sudo -u shop .venv/bin/python manage.py restore_backup /var/backups/shop/shop-YYYYMMDD-HHMMSS.dump \
     --media /var/backups/shop/shop-YYYYMMDD-HHMMSS-media.tar.gz --confirm
sudo systemctl start shop-gunicorn
```

It saves the current database to `BACKUP_DIR/before-restore/` first, so a
restore of the wrong file can be undone.

### Error alerts (email)

So that a crash at the till reaches you, not just a log file. Add to
`backend/.env` (any SMTP account works — e.g. a Gmail app password, or
your domain's mail server):

```bash
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=alerts@example.com
EMAIL_HOST_PASSWORD=<app password>
DEFAULT_FROM_EMAIL=Shop ERP <alerts@example.com>
ADMINS=Your Name:you@example.com
```

Restart gunicorn, then check mail works:
`sudo -u shop .venv/bin/python manage.py sendtestemail --admins`.

### Uptime monitoring

Point a free monitor (UptimeRobot, Better Stack…) at
`https://shop.example.com/api/health/`, checking every 5 minutes and
alerting you by SMS/email. It returns 503 if the database is unreachable
or the newest backup is older than `BACKUP_MAX_AGE_HOURS` (default 26).

### SMS end-of-day summaries (Beem Africa)

1. Open an account at [beem.africa](https://beem.africa), buy SMS credit,
   and apply for a sender ID (e.g. your shop's name; approval takes a
   few days — until then Beem's default `INFO` works).
2. Add to `backend/.env`, then restart gunicorn:
   ```bash
   SMS_PROVIDER=beem
   BEEM_API_KEY=<from Beem: Profile > Authentication information>
   BEEM_SECRET_KEY=<same place>
   BEEM_SENDER_ID=INFO
   ```
3. In the app: managers add their mobile number under *Edit my details*;
   an admin switches SMS on under Settings → Notifications and presses
   *Send test SMS*.
4. Switch on the evening timer (21:30 — set the server's time zone first):
   ```bash
   sudo timedatectl set-timezone Africa/Dar_es_Salaam
   sudo cp /opt/shop/deploy/systemd/shop-daily-summary.{service,timer} /etc/systemd/system/
   sudo systemctl daemon-reload && sudo systemctl enable --now shop-daily-summary.timer
   ```

   Analytics needs no timer: the Analytics screen reads the sales, stock
   and purchase records directly, so it is always current.

   **Upgrading a server that had the old nightly analytics refresh?** The
   `rebuild_analytics` command it ran no longer exists, so switch it off
   (it would otherwise fail every night at 01:30):

   ```bash
   sudo systemctl disable --now shop-analytics.timer
   sudo rm /etc/systemd/system/shop-analytics.{service,timer}
   sudo systemctl daemon-reload
   ```

### Sign-in security

Sessions end `TOKEN_TTL_HOURS` (default 14) after sign-in, and 5 wrong
passwords lock a username for 15 minutes (`LOGIN_LOCKOUT_ATTEMPTS`,
`LOGIN_LOCKOUT_MINUTES`). An admin who sets a staff member's password
signs them out everywhere, and they must choose their own at next sign-in.
Every sign-in, failed sign-in, price change, void, write-off, stock-count
approval and staff change is in Admin → Activity log.

## Redeploying after a code change

```bash
cd /opt/shop && sudo -u shop git pull
cd backend && sudo -u shop .venv/bin/python manage.py migrate
sudo -u shop .venv/bin/python manage.py collectstatic --noinput
cd ../frontend && sudo -u shop npm ci && sudo -u shop npm run build
sudo systemctl restart shop-gunicorn
```

nginx needs no restart unless `shop.example.com.conf` itself changed.

## Troubleshooting

- **502 Bad Gateway**: gunicorn isn't running or isn't listening on
  `127.0.0.1:8000`. Check `sudo systemctl status shop-gunicorn` and
  `sudo journalctl -u shop-gunicorn -n 50`.
- **400 Bad Request** (plain text, not a Django page): the domain isn't in
  `ALLOWED_HOSTS` in `.env` — Django deliberately rejects unrecognized
  `Host` headers.
- **CSRF / "Origin checking failed"** on admin login: `.env`'s
  `CSRF_TRUSTED_ORIGINS` doesn't include `https://shop.example.com`
  (must have the `https://` scheme, not just the bare domain).
- **certbot fails with a connection/timeout error**: DNS hasn't propagated
  yet (recheck with `dig`), or port 80 isn't reachable (check `ufw status`
  and that nginx is actually running).
- **Frontend loads but every request fails**: `CORS_ALLOWED_ORIGINS` /
  `CSRF_TRUSTED_ORIGINS` in `.env` don't include the site's `https://`
  address, or gunicorn is down (see 502 above).
- **"Too many wrong passwords"**: wait `LOGIN_LOCKOUT_MINUTES`, or have an
  admin set a new password for that user (Admin → Users).
- **Nightly backup failed** (`systemctl status shop-backup`): usually a
  full disk (`df -h`), `BACKUP_DIR` not writable by the `shop` user, or
  `pg_dump` missing (`apt install postgresql-client`).
- **Static files 404 in `/admin/`**: `collectstatic` wasn't run, or the
  `shop` user can't read `backend/staticfiles` — rerun
  `manage.py collectstatic --noinput` and check ownership
  (`chown -R shop:shop /opt/shop`).
