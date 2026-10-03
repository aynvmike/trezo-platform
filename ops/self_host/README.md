# Trezo: self-hosted database migration preparation

Status: preparation tooling, **not a deployed database or an executed migration**.
The managed database was observed failing recovery with PostgreSQL `53100` (disk full)
on October 3, 2026. A dashboard health badge does not prove it can accept SQL. A readable
full source or a verified full backup is a prerequisite; the current agent archive is
not one. It only samples selected tables and omits settings/auth and other state.

The first migration preserves Supabase APIs, Auth, RLS and the three books. Replacing
them with plain Postgres immediately would require application changes throughout the
web/API/agents. Self-hosting removes the managed database subscription, but still needs
host capacity, patching, monitoring and backups. It does not establish a trading edge.

## 1. Host and recovery gates

1. Run `ops/host_preflight.ps1` on TrezoServer and save its receipt privately. Current
   documentation identifies Windows Server 2022 on Lightsail. **Do not install Docker
   Desktop on that server**: Docker does not support Desktop on Windows Server.
   Do not assume nested virtualization or WSL2 works on its instance class.
2. Confirm an existing supported Linux host/VM and its storage/backup capacity. If this
   needs another paid instance, present its actual cost before provisioning. Do not
   rebuild the existing Windows host in place to obtain Linux.
3. On the proposed Linux host, run:

   ```sh
   python3 ops/self_host/linux_preflight.py --data-directory /srv
   ```

   This checks available memory, CPUs, free disk and a local Linux Docker Engine/Compose.
   Its conservative lower bounds are 4 GiB available memory, two CPUs and 40 GiB free
   disk. `CANDIDATE` is only a point-in-time capacity check. Reserve resources for Trezo,
   Docker/WAL, dump files, restores and backup encryption; validate peak load. Confirm
   actual SSD storage, Docker resource limits, retention and independent disk alerts.
4. Restore management access independently of the broken database. Use the authenticated
   existing Tailscale/RDP host connection and `ops/host_maintenance.ps1`; the Supabase
   `ops_tasks` relay and GitHub relay cannot recover their own unavailable database.
   Do not expose an unauthenticated command endpoint or public Postgres port.
5. Recover the source through Supabase's supported disk-recovery/support path, or obtain
   a verified full backup and record its recovery point. Do not delete WAL files, reset
   Postgres, drop tables, or pause/delete the hosted project to “free space.” A temporary
   paid recovery action, if needed, is a separate cost decision. Zeroed charts are not
   evidence that space was freed.

## 2. Prepare the official stack without starting it

Use the official [Docker guide](https://supabase.com/docs/guides/self-hosting/docker)
and [release history](https://github.com/supabase/supabase/tags). The guide observed on
October 3 names `self-hosted/v0.8.2`. The official GitHub annotated tag
`47111f95a43ffcc20ab288e29c48ce0b80174bd6` resolves to commit
`564eab8ad7840b13324f68b1bfac074ef8d51c21` (verified using the
[official tag API](https://api.github.com/repos/supabase/supabase/git/tags/47111f95a43ffcc20ab288e29c48ce0b80174bd6)).
Use this verified pin for preparation; its compatibility with Trezo's recovered source
has **not** been tested:

```sh
sh ops/self_host/prepare_official.sh 564eab8ad7840b13324f68b1bfac074ef8d51c21 /srv/trezo-supabase-staging
```

This only copies `docker/` from the fixed official Supabase repository, checks the
fetched commit, and records it. It does not execute upstream scripts, generate secrets,
pull images or start containers. A failed fetch leaves `PREPARATION_INCOMPLETE`.
Use a private directory outside the Trezo Git checkout. Review the pinned Compose and
scripts before executing anything; record the image digests actually pulled too.

Before first start, generate fresh secrets with the pinned upstream instructions in a
private terminal; never post their output or `.env`. Do not use example credentials.
Configure HTTPS on the private Tailscale-accessible hostname, Auth site/redirect URLs,
SMTP and any OAuth providers. Bind the API gateway and all published database/pooler
ports to loopback or the intended private interface, and test access from both allowed
and disallowed networks. Compose defaults alone are not proof of private bindings.
Keep Studio private. Do not expose the Docker socket. Check resolved ports with a
local-only inspection; a full `docker compose config` can print secrets.

Avoid enabling optional analytics/log ingestion until its capacity and bounded
retention have been reviewed. Preserve required API/Auth/Storage capabilities. Do not
remove services blindly to force the stack onto an undersized server.

Start an isolated **test** stack using that release's instructions. The Trezo agent,
API and web services must not point to it yet. Match the source Postgres major version
and required extensions where possible; mixed Auth/Storage versions need a rehearsal.

## 3. Export, encrypt, and prove recovery

Follow the official [platform restore procedure](https://supabase.com/docs/guides/self-hosting/restore-from-platform).
Its three exports are roles, schema and data using Supabase CLI (`--role-only`, normal
schema dump, and `--data-only --use-copy`). This includes Auth users, RLS/functions and
triggers. Use a reviewed/pinned CLI version with Docker available. Record the source
Postgres/extension and CLI versions. Raw `pg_dump` without Supabase filtering is not a
drop-in substitute for this import procedure.

Connection strings and passwords are secrets. Run exports in a private host session;
use the CLI's supported environment/password mechanism for the pinned version and
avoid putting literal credentials in shell history or shared logs. Dumps contain
private ledger and Auth data even when roles do not include passwords. Put all exports
in a restricted directory outside Git; never attach them to a public issue or PR.

For the **final** export, stop every writer: TrezoAgents, API/web routes and scheduled
tasks that write, all other engine instances, cloud briefings/relays, and applicable
database cron jobs. Record stopped service/task identities. An agent's trading-mode
switch alone does not stop background writes. Keep existing broker-side protection;
stopping the engine also stops software-managed monitoring. Inspect open broker orders
and arrange supervision for the maintenance window. Never run source and target engines
together. Separate CLI dumps need this freeze to describe the same point in time.

Copy Storage object **bytes** separately with the official
[Storage migration guide](https://supabase.com/docs/guides/self-hosting/copy-from-platform-s3).
Database rows for buckets/objects are metadata, not a file backup. Inventory each key,
size and SHA-256; compare to the destination. Use its S3 transfer procedure, not a raw
download copied into the self-hosted Storage volume. Export required Edge Functions and their
private configuration separately. Preserve the source `.env` files in encrypted recovery
material, not Git, and keep Alpaca key-slot mapping unchanged. Fresh self-hosted API/JWT
keys require application configuration updates and users signing in again.

Before cutover, encrypt the SQL, Storage objects, private manifests, config and recovery
instructions using an established tool such as age/GPG; do not invent encryption.
Copy the encrypted bundle off the database host to storage Mike already controls.
Keep the decryption key separately. Record a receipt with UTC time, recovery point,
encrypted bundle SHA-256/size, off-host destination, retrieved-copy checksum and the
successful decrypt/restore rehearsal result. A local archive or successful upload
alone does not prove recovery. Do not remove the hosted source or backups.

## 4. Compare the books and complete state

`verify_migration.py` uses installed `psql` and standard Python only. It cannot restore,
change settings, place trades or authorize cutover. Configure `trezo-source` and
`trezo-target` libpq service profiles and passfiles in private OS-protected locations
(`PGSERVICEFILE`/`PGPASSFILE`). For source use verified TLS; for target use the private
trusted route. Use a role able to read every inventoried table: missing privileges are
a failure, never an empty count. Connection passwords are not CLI arguments.

Create a private `books.json` mapping the existing environment slots to their exact
UUIDs. Read the values locally from the host; do not create new book identities:

```json
{
  "primary": "VALUE_OF_TREZO_PRIMARY_USER_ID",
  "acct2": "VALUE_OF_TREZO_ACCOUNT_USER_ID_2",
  "acct3": "VALUE_OF_TREZO_ACCOUNT_USER_ID_3"
}
```

After the final freeze, capture the recovered source. Restore roles/schema/data to the
isolated target with the official single-transaction, `ON_ERROR_STOP` procedure and its
documented replication-role setting. Do not omit incompatible rows to make restore
green; investigate and rehearse version alignment. Then capture the target before any
application or user login changes its data:

```sh
python3 ops/self_host/verify_migration.py capture --service trezo-source \
  --books /private/trezo/books.json --writers-stopped --out /private/trezo/source.json
python3 ops/self_host/verify_migration.py capture --service trezo-target \
  --books /private/trezo/books.json --writers-stopped --out /private/trezo/target.json
python3 ops/self_host/verify_migration.py compare /private/trezo/source.json /private/trezo/target.json
```

`--writers-stopped` is the operator's attestation, not a stop command. Output files must
be new and outside Git. POSIX files use mode 0600; on Windows also enforce directory
ACLs. Each capture uses a repeatable-read, read-only transaction. It fingerprints every
public table's full rows plus Auth users/identities and Storage buckets/objects; it
validates three active Alpaca paper books, owner existence and exactly one settings and
paper-account row per book. Same count with changed settings/P&L/positions is blocked.
Extra/missing tables, slot swaps and missing reads are blocked too. No row values or
credentials are printed. Large tables may hit the read-only timeout: treat that as
incomplete and arrange a controlled inventory window, never skip them for a “pass.”

`MATCH` is **row consistency only**. Separately compare the restored schema, constraints,
indexes, RLS/policies, grants, functions, triggers, migrations and required extensions;
check all other application schemas and Auth service internals through the full restore
rehearsal. Test owner login, non-owner denial, dashboard/SSR auth and a book-scoped read.
MD5 row fingerprints detect accidental differences; use SHA-256 of encrypted artifacts
for transfer integrity. Neither replaces a verified backup or broker reconciliation.

## 5. Controlled cutover and rollback

Once restore, off-host recovery, identity, schema/RLS, Storage and private-network tests
pass, preserve the old application env files encrypted. Update Supabase URL/server keys
in `agents/.env`, `api/.env` and `web/.env.local`; public URL/anon or publishable values
embedded into Next.js require a rebuild. Verify the current client versions accept the
chosen key format and RLS still applies. Never put service-role/secret keys into public
Next.js variables. Change only database connectivity, not Alpaca keys or risk budgets.

Keep entries paused until each book has fresh, successful **strict** Alpaca reads of
account, open positions, orders and fills, and ledger/broker discrepancies are resolved
or explicitly flagged. A failed read must not flatten a book. Confirm crypto-only entry
settings and all risk controls survived exactly; preserve exit management of any old
non-crypto holdings. Test the existing read-only crypto audit against the new database.
Do not manufacture orders to make a dashboard look active.

Start only the one intended engine after checks; verify its commit, registry, per-book
quote freshness and real signal → verdict → execution/rejection/refusal receipts.
Distinguish intentional vetoes from missing outcomes. Observe the runtime symptom,
not merely a green deploy. Check direct host maintenance still works if the DB is stopped.

If failure occurs **before target writes**, stop all target application services,
restore the original env/rebuild, verify the recovered source still matches the final
freeze and reconcile broker state before resuming its single writer. If the target has
written or submitted any order, do **not** point back to a stale source: stop new
entries, preserve target changes and reconcile/migrate the delta with broker receipts.
Do not reset volumes or delete either copy to simplify rollback.

Acceptance remains blocked until these receipts exist. This kit changes no production
configuration and does not claim a recovery point that has not been tested.

## Offline checks

```sh
python3 -m unittest discover -s ops/self_host -p 'test_*.py'
sh -n ops/self_host/prepare_official.sh
```

The synthetic checks cover failure-vs-empty, changed rows at equal counts, missing
tables, independent book identities, private file handling and a compare that cannot
authorize cutover. They do not execute SQL against the unreachable source, fetch upstream
infrastructure or prove a target deployment. The repository's normal agent deploy gate
and pytest still apply to any accompanying runtime changes.

Primary references checked October 3, 2026: the Supabase Docker/restore guides above;
[Docker Desktop Windows support](https://docs.docker.com/desktop/setup/install/windows-install/).
