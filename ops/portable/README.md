# Move Trezo off AWS

This is an operator-run migration package. It has **not** restored a database,
installed a replacement server, or started Trezo. GitHub contains the code and these
tools; it does not contain the three environment files, book data or database backup.
Keep encrypted recovery bundles and all decrypted files outside GitHub and outside any
Git checkout. Do not paste credentials, dumps or environment files into chat.

You can manage the old and new servers from a phone using their authenticated browser
console or a private SSH/remote-desktop connection. The phone does not need to run the
agents or database. This procedure targets a native Linux server with systemd; it is
not an Android/Termux installation or a Windows-to-Linux in-place conversion.

## What is ready, and what still blocks a move

| Receipt | What it establishes | What it does not establish |
| --- | --- | --- |
| Encrypted host export, `HOST_ONLY` | The included credentials and local state were saved | Supabase ledger/Auth/settings recovery |
| `RECOVERY_MATERIAL_PRESENT_UNVERIFIED` | Required database files and host files are present and checksummed | SQL compatibility or a successful restore |
| Installer `PREPARED_NOT_BUILT_NOT_ACTIVE` | Private copies, paths and unit templates were prepared | Dependencies, database or running services |
| Installer `BUILT_NOT_ACTIVE` | Dependencies, application builds and agent guard suites passed | Database recovery or permission to activate |
| Database `DATABASE_ROWS_MATCH` | Inventoried source and restored target rows agree | Storage bytes, schema/RLS, Auth configuration or broker agreement |
| Checker `CHECKS_PASSED` | Requested configuration/process checks passed | Trading readiness, profitability or a complete recovery test |

The hosted Supabase database was observed refusing connections after a disk-full
recovery failure. Recover a readable source through supported recovery, or obtain and
verify a complete backup. If neither exists, **stop at host preservation and target
preparation**. A new empty database is not a restored ledger. The hourly agent archive,
sampled rows, a code ZIP and a green dashboard do not substitute for a full backup.

The three existing books remain `primary`, `acct2` and `acct3`, with their original
UUIDs, separate Alpaca paper credentials, positions, settings and risk controls.
Preserve crypto-only **new entries**; preserve exit/protection management of existing
non-crypto positions. Do not create new book identities or reset balances to make a
migration appear complete.

## 1. Preserve the source before retiring AWS

Use an authenticated Windows administrator session. Install the reviewed [`age` CLI](https://github.com/FiloSottile/age#installation)
if it is absent; Python and Git must already be available. Acquire these tools in a
**separate** new code checkout, not by pulling the running engine checkout:

```powershell
$ToolRepo = 'C:\Trezo\portable-tools'
$ReviewedCommit = 'PASTE_REVIEWED_FULL_40_CHARACTER_COMMIT'
git clone --single-branch --branch codex/portable-migration-20261004 https://github.com/aynvmike/trezo-platform.git $ToolRepo
if ($LASTEXITCODE -ne 0) { throw 'Clone failed' }
$ActualCommit = (git -C $ToolRepo rev-parse HEAD).Trim()
if ($ActualCommit -ne $ReviewedCommit) { throw 'Branch moved or incorrect reviewed commit' }
git -C $ToolRepo checkout --detach $ReviewedCommit
if ($LASTEXITCODE -ne 0) { throw 'Checkout failed' }
```

Obtain the reviewed full SHA from the release/PR, compare it to `git rev-parse HEAD`,
and retain it for the Linux installation. A branch name or short SHA is not the pin.
If a later release changes the branch name, use that reviewed release explicitly.

Create `C:\Trezo\private-migration` and a `work` subdirectory outside all Git checkouts.
Restrict their NTFS permissions to the operator, SYSTEM and Administrators, removing
inherited general-user access. The backup tool cannot verify Windows ACLs. Keep enough
free disk for the plaintext staging, SQL and encrypted output; `age -p` prompts in the
terminal, so no passphrase belongs in an argument or environment variable.

Before the final snapshot, record and pause every automatic starter/updater and writer.
Inspect task **names and states** first:

```powershell
Get-ScheduledTask | Where-Object { $_.TaskName -like '*Trezo*' } | Select-Object TaskName, TaskPath, State
Get-Service TrezoAgents, TrezoApi, TrezoWeb
```

Disable the installed Trezo watchdog/auto-pull tasks and any queued
`TrezoRelayRestart*` tasks using Task Scheduler; stop any that are running. Also check
tasks with different names whose actions launch Trezo, other machines running an
engine, cloud relays/briefings and database cron writers. Record their original states
for rollback. Do not blindly disable unrelated tasks. Then stop the actual NSSM
services and verify each is stopped:

```powershell
$Nssm = 'C:\ProgramData\chocolatey\bin\nssm.exe'
& $Nssm stop TrezoWeb
& $Nssm stop TrezoApi
& $Nssm stop TrezoAgents
Get-Service TrezoAgents, TrezoApi, TrezoWeb
```

Service names/locations must match the source host. Verify no independent Trezo
process remains and no task restarts it. Stopping the engine also stops software
position monitoring; inspect existing broker-side orders/protection and supervise the
maintenance window. The `--writers-stopped` flags below **attest** this work; they do
not stop anything themselves.

Preserve host material immediately even if Supabase is unavailable:

```powershell
python "$ToolRepo\ops\portable\backup.py" export --repo C:\Trezo\trezo-platform --out C:\Trezo\private-migration\trezo-host.age --work-directory C:\Trezo\private-migration\work --writers-stopped --passphrase
```

An `INCOMPLETE` result requires investigation. A `HOST_ONLY` result can preserve the
host but cannot restore its ledger. Custom state paths such as
`TREZO_RESEARCH_DB_PATH` require a separate reviewed export and relocation; no tool
guesses their contents or rewrites them silently.

### Add full database recovery material when it becomes readable

Follow the [existing self-host recovery runbook](../self_host/README.md#3-export-encrypt-and-prove-recovery)
and the [official platform restore procedure](https://supabase.com/docs/guides/self-hosting/restore-from-platform).
Use a pinned Supabase CLI, verified source project/connection and its private password
mechanism. Export **roles**, **schema**, and **data with COPY**; do not substitute a raw
`pg_dump` of Supabase internals or apply application migrations to invent missing data.
Keep all source writers stopped across the separate exports and source inventory.

Prepare a restricted database export directory outside Git containing:

| Required path | Source |
| --- | --- |
| `roles.sql` | Official CLI role-only export |
| `schema.sql` | Official CLI schema export |
| `data.sql` | Official CLI data-only export with `--use-copy` |
| `books.json` | Original three book UUIDs, keyed `primary`, `acct2`, `acct3` |
| `source-inventory.private.json` | Frozen-source capture command below |
| `storage/` | Object bytes plus reviewed key/size/SHA-256 inventory, including an explicitly verified empty set when applicable |

In `books.json`, copy the existing values of `TREZO_PRIMARY_USER_ID`,
`TREZO_ACCOUNT_USER_ID_2` and `TREZO_ACCOUNT_USER_ID_3` into the corresponding slots.
Also preserve required Edge Functions, Auth provider/SMTP/redirect configuration,
source Postgres/extension versions and recovery instructions privately. Database
Storage rows describe objects; they do not contain all object bytes. Follow the
[supported Storage/S3 transfer procedure](https://supabase.com/docs/guides/self-hosting/copy-from-platform-s3).

Configure private libpq source service/passfiles, with verified TLS to the source.
Set `PGSERVICEFILE` and `PGPASSFILE` to their **file paths**, not passwords. For example:

```powershell
python "$ToolRepo\ops\self_host\verify_migration.py" capture --service trezo-source --books C:\Trezo\private-migration\database\books.json --writers-stopped --out C:\Trezo\private-migration\database\source-inventory.private.json
python "$ToolRepo\ops\portable\backup.py" export --repo C:\Trezo\trezo-platform --database-export-dir C:\Trezo\private-migration\database --out C:\Trezo\private-migration\trezo-complete.age --work-directory C:\Trezo\private-migration\work --writers-stopped --passphrase
```

Every output must be new. A failed read is a failure, never an empty table. Copy the
encrypted bundle to storage off AWS that the owner controls, keep its passphrase or
private identity separately, download it again, compare its SHA-256 and test decryption.
Record the UTC recovery point and checksum. Do not upload the bundle to the public
repository, even though it is encrypted.

## 2. Prepare a fresh Linux host and reviewed checkout

Use Ubuntu/Debian or another supported native Linux/systemd host. The administrator
prepares Python 3.11+ with venv, Node 20+, npm, Git, util-linux `flock`, `age`, PostgreSQL
`psql`, Docker Engine and Docker Compose **2.24.4 or newer**. The scripts do not install
these packages, buy a server or accept a provider's contract.

The [official Supabase requirements](https://supabase.com/docs/guides/self-hosting/docker#system-requirements)
are 4 GB RAM, 2 CPU cores and 40 GB SSD minimum; 8 GB+, 4 cores+ and 80 GB+ SSD are
recommended. Those figures are for Supabase. Trezo's agents, Next.js builds, retained
logs, database WAL, restore staging and backups need additional headroom. Validate
actual peak load and free disk. A low advertised VPS price is not a verified monthly
total or proof of adequate capacity.

Use a dedicated unprivileged `trezo` account. An administrator creates the account and
parent directories first; never run the application installer as root. Example for a
new Debian/Ubuntu host, after checking that these names and paths are unused:

```sh
sudo adduser --disabled-password --gecos '' trezo
sudo install -d -o trezo -g trezo -m 0750 /srv/trezo
sudo install -d -o trezo -g trezo -m 0700 /srv/trezo/private
sudo -iu trezo
```

In the `trezo` shell, set the reviewed release SHA and clone the code:

```sh
set -eu
umask 077
TREZO_REVIEWED_COMMIT='PASTE_REVIEWED_FULL_40_CHARACTER_COMMIT'
git clone --single-branch --branch codex/portable-migration-20261004 https://github.com/aynvmike/trezo-platform.git /srv/trezo/app
test "$(git -C /srv/trezo/app rev-parse HEAD)" = "$TREZO_REVIEWED_COMMIT"
git -C /srv/trezo/app checkout --detach "$TREZO_REVIEWED_COMMIT"
mkdir -m 700 /srv/trezo/private/work
```

The checkout and private state are **siblings**, not nested. The private directory
must not be in any Git checkout, and installation roots must not contain symlinks.
Keep `.git` metadata: process/commit verification depends on it.

Copy the verified encrypted bundle into `/srv/trezo/private/trezo-complete.age` using
an authenticated private transfer. Restrict the file to mode 0600. Inspect and restore
into a **new**, immutable staging directory:

```sh
cd /srv/trezo/app
python3 ops/portable/backup.py inspect /srv/trezo/private/trezo-complete.age --work-directory /srv/trezo/private/work
python3 ops/portable/backup.py restore /srv/trezo/private/trezo-complete.age --work-directory /srv/trezo/private/work --dest /srv/trezo/private/restore
```

For recipient encryption, add `--identity /private/path/to/age-identity` to both
commands. Keep that identity mode 0600 and outside Git. Never edit files under
`private/restore`: their hashes are validated before installation and database import.

## 3. Prepare application files; relocate only the copies

Still as `trezo`, before any application starts:

```sh
python3 ops/portable/install.py prepare --checkout /srv/trezo/app --private-root /srv/trezo/private --restore-root /srv/trezo/private/restore/host --expected-commit "$TREZO_REVIEWED_COMMIT" --service-user trezo
```

This copies the three env files to `private/runtime/agents/.env`,
`private/runtime/api/.env` and `private/runtime/web/.env.local`, links the checkout to
them, and renders units into `private/units`. Most runtime directories also point into
private state. The five app JSON caches remain private files in their ignored checkout
locations because they use atomic writers. The knowledge library keeps its one
versioned file; restored private additions are copied into ignored paths beside it.
Existing conflicting content is never overwritten. No service is installed or started.

Now edit **only the private runtime copies**, using a private editor. Set the target
Supabase URL and matching compatible server/public keys across all components. Change
the dashboard URL and old Windows/host paths; review custom research/memory paths
separately. Server service keys must never go into a `NEXT_PUBLIC_*` variable. Preserve
the three book UUIDs, three distinct Alpaca paper key pairs, risk controls and
`TRADING_MODE=paper`. Keep `TREZO_ACCOUNTS_ENABLED=primary,acct2,acct3` and the approved
Alpaca crypto route. Keep private service connections on loopback:

| Service | Address |
| --- | --- |
| Agents | `http://127.0.0.1:8001` |
| Express API | `http://127.0.0.1:8000` |
| Dashboard | `http://127.0.0.1:3000` |
| Supabase gateway, with the supplied override | `http://127.0.0.1:54321` |
| Direct Postgres, import only | `127.0.0.1:54322` |

The browser needs reachable private HTTPS URLs for the dashboard and Supabase, through
an authenticated/private network and a reviewed reverse proxy. `127.0.0.1` in a phone's
browser points to the phone, not the server. Configure DNS, TLS, Supabase Auth site and
redirect URLs, and firewall rules before relying on login. Do not publish Postgres,
Studio or the application ports directly to the Internet.

Build after the env relocation, since Next.js embeds public variables at build time:

```sh
python3 ops/portable/install.py build --checkout /srv/trezo/app --private-root /srv/trezo/private --expected-commit "$TREZO_REVIEWED_COMMIT" --service-user trezo
/srv/trezo/app/agents/.venv/bin/python ops/portable/check.py --repo /srv/trezo/app --books /srv/trezo/private/restore/database/books.json --supabase-url https://YOUR-PRIVATE-SUPABASE-HOST --web-url https://YOUR-PRIVATE-TREZO-HOST
```

The build creates a new agents venv, runs `npm ci` once at the workspace root, builds
API/web, then runs the actual agent guard suites in a separate credential-free
checkout. It never boots the trading application. `private/install/build.log` records
step outcomes/timings only; subprocess output is suppressed to avoid leaking secrets.
A failed build produces no success receipt and starts nothing. Existing build
destinations are refused; diagnose privately and use a reviewed fresh installation,
preserving the source bundle. Do not delete runtime data to force a retry.

## 4. Bootstrap and restore an isolated Supabase target

The database procedure is separate from application preparation. Docker management
requires its own appropriate administrator permissions; do not grant the application
service broad privileges merely to manage Docker. Run this part in a private admin
session that can access the private stack files.

First run the existing capacity check against the intended disk:

```sh
python3 /srv/trezo/app/ops/self_host/linux_preflight.py --data-directory /srv/trezo/private
```

`CANDIDATE` checks only current lower bounds; it is not a capacity guarantee. Prepare
the reviewed official `self-hosted/v0.8.2` source, pinned to its full commit:

```sh
sh /srv/trezo/app/ops/self_host/prepare_official.sh 564eab8ad7840b13324f68b1bfac074ef8d51c21 /srv/trezo/private/supabase
```

The preparation script only fetches/copies configuration. Follow that pinned release's
manual setup to generate fresh private secrets and configure its URLs, database,
Auth/SMTP/providers and supported API key formats. Rehearse Postgres/extensions and
Auth/Storage version compatibility with the recovered source. Never use shipped
example passwords, display the full Compose config in shared logs or print secrets
into this chat.

Use **both** Compose files for every stack operation; the override replaces gateway
bindings with loopback 54321, publishes direct DB on loopback 54322, and removes pooler
host publication. Keep the stack's internal `POSTGRES_PORT=5432`; 54322 is only the
host-side import port. Compose 2.24.4+ is required for `!override`. Run the read-only
merged-config verifier and require `status: pass` before starting any containers:

```sh
set -eu
cd /srv/trezo/private/supabase/stack
python3 /srv/trezo/app/ops/portable/verify_compose.py --stack /srv/trezo/private/supabase/stack
docker compose --env-file .env -f docker-compose.yml -f /srv/trezo/app/ops/portable/supabase-loopback.yml up -d --wait
docker compose --env-file .env -f docker-compose.yml -f /srv/trezo/app/ops/portable/supabase-loopback.yml stop
docker compose --env-file .env -f docker-compose.yml -f /srv/trezo/app/ops/portable/supabase-loopback.yml up -d --no-deps db
docker compose --env-file .env -f docker-compose.yml -f /srv/trezo/app/ops/portable/supabase-loopback.yml ps
```

Bootstrap first so Auth/Storage schemas exist; then leave **only `db` running** for
import. Stopping the whole stack pauses Studio, api-gw, Auth, REST, Realtime, Storage,
imgproxy, meta, functions, Supavisor and any included extra clients; `--no-deps` starts
only the database again. If external custom services exist, stop their database clients too. Trezo, user
logins and other database clients must remain stopped. The restore helper verifies
no other client connections and empty application/Auth/Storage data. Fresh
`auth.schema_migrations` metadata is the sole populated Auth-table exception. Never
delete target data or kill unknown sessions merely to make its preflight pass.

As `trezo`, create a mode-0600 libpq service file outside the bundle, for example
`/srv/trezo/private/pg_service.conf`. Its target stanza is:

```ini
[trezo-target]
host=127.0.0.1
port=54322
dbname=postgres
user=postgres
sslmode=disable
```

Create a separate mode-0600 `/srv/trezo/private/pgpass` with the matching local
host/port/database/user and target password, entered privately with libpq escaping.
Its field order is `127.0.0.1:54322:postgres:postgres:PRIVATE_TARGET_PASSWORD`;
replace that placeholder in the private editor and escape `:` and `\` with `\`.
This is a direct database superuser connection, not a pooler username or source
credential. `sslmode=disable` here applies only to the forced loopback import route.
Both files and their parent directories must be owned/protected appropriately.

Run preflight, then the explicitly authorized import into this unused target:

```sh
cd /srv/trezo/app
python3 ops/portable/database.py preflight --bundle /srv/trezo/private/restore --books /srv/trezo/private/restore/database/books.json --service trezo-target --service-file /srv/trezo/private/pg_service.conf --passfile /srv/trezo/private/pgpass --port 54322
python3 ops/portable/database.py restore --bundle /srv/trezo/private/restore --books /srv/trezo/private/restore/database/books.json --service trezo-target --service-file /srv/trezo/private/pg_service.conf --passfile /srv/trezo/private/pgpass --port 54322 --target-inventory /srv/trezo/private/target-inventory.private.json --confirm-empty-target --writers-stopped
```

The helper validates bundle hashes and book identities, imports the original roles,
schema and data with `ON_ERROR_STOP` in one transaction, and compares a new target row
inventory with the frozen source. Output inventory is outside the immutable bundle.
If SQL succeeds but inventory verification fails, **keep all writers stopped and do
not rerun restore into the now-populated target**. Inspect privately. Do not omit
incompatible rows, reset volumes or invent defaults to get a passing result.

After a row match, restore Storage object bytes through the supported S3/API procedure
and compare key/size/checksum inventories. Check schema, constraints, indexes, RLS,
policies, grants, functions, triggers, migrations and extensions separately. Bring up
only required Supabase clients for this verification; keep every Trezo engine stopped.
Test owner login, non-owner denial, three book-scoped reads and private HTTPS access.
New JWT/API keys and Auth configuration can require users to sign in again. A row match
does not authorize application activation.

## 5. Activate one engine only after the restore is proven

Before starting any Trezo service, retain evidence of all of the following:

- An off-host encrypted bundle was retrieved, decrypted and successfully rehearsed.
- Source/target book rows match; full schema/RLS, Auth and Storage checks pass.
- All three original paper books retain crypto-only entry settings and risk limits.
- Fresh strict Alpaca account/position/order/fill reads succeed for each book; ledger
  differences are reconciled or explicitly flagged. A failed read never means flat.
- The configuration checker passes with the target URLs and the application build
  receipt has the exact reviewed commit.
- The **old engine and all its automatic starters remain stopped**, with no second
  engine on another host. Resolve current broker protection/monitoring responsibilities.

Starting the agents runs startup repair and background writers immediately. Do not
start it merely to inspect configuration or before these checks. The systemd flock
prevents another launcher using the same lock; it cannot stop an engine on AWS or a
manual process bypassing the lock.

Only after explicit cutover approval, an administrator installs the three rendered
unit files and reloads systemd. Confirm those unit destinations do not already exist:

```sh
sudo install -o root -g root -m 0644 /srv/trezo/private/units/trezo-agents.service /etc/systemd/system/trezo-agents.service
sudo install -o root -g root -m 0644 /srv/trezo/private/units/trezo-api.service /etc/systemd/system/trezo-api.service
sudo install -o root -g root -m 0644 /srv/trezo/private/units/trezo-web.service /etc/systemd/system/trezo-web.service
sudo systemctl daemon-reload
TREZO_STARTED_AFTER=$(date -u +%Y-%m-%dT%H:%M:%SZ)
sudo systemctl start trezo-agents.service trezo-api.service trezo-web.service
```

Run process verification in a session with permission to inspect the `trezo` processes
and listeners; retain the timestamp and reviewed SHA from above:

```sh
/srv/trezo/app/agents/.venv/bin/python /srv/trezo/app/ops/portable/check.py --repo /srv/trezo/app --books /srv/trezo/private/restore/database/books.json --supabase-url https://YOUR-PRIVATE-SUPABASE-HOST --web-url https://YOUR-PRIVATE-TREZO-HOST --runtime --expected-commit "$TREZO_REVIEWED_COMMIT" --started-after "$TREZO_STARTED_AFTER"
```

Require the owned Python PID, fresh engine boot beacon, expected commit and local
health/listeners to agree. Then verify fresh quotes separately for each book and
observe real signal → verdict → execution/rejection/refusal receipts. Intentional
vetoes are different from missing outcomes. Test the read-only crypto audit and
owner dashboard; do not create test orders merely to produce activity. Enable boot
startup only after the accepted observation period:

```sh
sudo systemctl enable trezo-agents.service trezo-api.service trezo-web.service
```

Linux intentionally disables the old Windows deployment/restart relay mutations.
Use direct authenticated host access for maintenance. A green process check does not
prove an economic edge or replace ongoing per-book monitoring and disk/backup alerts.

## 6. Roll back carefully, then retire old billing

If target applications have **not written**, stop/disable every target Trezo service,
verify no target engine remains, preserve diagnostics, and re-check the frozen source
plus current broker state before resuming its single engine. Re-enable only the
source tasks that were enabled before maintenance. A still-unreadable source database
cannot support a safe rollback to trading.

If target applications wrote data or submitted orders, the source is now stale. Stop
new entries, preserve target data and broker receipts, and reconcile/migrate the delta
before choosing one writer. Never run both engines, reset a database volume, or point
the old engine at a stale ledger as a shortcut.

After the new system and recovery test are accepted, create another encrypted,
off-host backup. On the installed Linux layout, pass the explicit private state root:

```sh
python3 /srv/trezo/app/ops/portable/backup.py export --repo /srv/trezo/app --host-state-root /srv/trezo/private/runtime --database-export-dir /srv/trezo/private/NEW-FROZEN-DATABASE-EXPORT --out /srv/trezo/private/NEW-BACKUP.age --work-directory /srv/trezo/private/work --writers-stopped --passphrase
```

The five current app JSON caches and the mixed tracked/private library are read from
the checkout; env files and other exported runtime directories come from private
state. Recreate current full database exports and inventory for each recovery point.
Confirm backup schedules, retention and independent disk alerts separately.

If AWS must be retired sooner, first verify an off-AWS encrypted host bundle and
retrieved-copy checksum/decryption, and explicitly accept any resulting downtime.
That preserves the host material; it does **not** resolve the separate unavailable
Supabase ledger. Do not delete the hosted Supabase project or its possible recovery
material. A stopped Lightsail instance still incurs instance charges; after verifying
preservation, delete retired AWS resources through the authenticated provider account
and inspect remaining snapshots, disks and addresses for separate charges. Resource
deletion is a separate explicit action, not performed by this package.

## Offline tests

```sh
python3 -m unittest discover -s ops/portable -p 'test_*.py'
python3 -m unittest discover -s ops/self_host -p 'test_*.py'
```

These synthetic tests do not boot Trezo or restore a live database. Actual Linux
installation, restore, off-host recovery and one-engine cutover need their own receipts.
