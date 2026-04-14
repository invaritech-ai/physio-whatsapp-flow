# Database Migration Runbook (Full Clone + Brief Downtime)

This runbook migrates the current production PostgreSQL database into a new PostgreSQL target using a full clone (schema + data), then performs cutover with fast rollback.

## 1) Preconditions

- `pg_dump` and `pg_restore` installed on the execution machine.
- Access to both databases:
  - `OLD_DATABASE_URL` (current production DB)
  - `NEW_DATABASE_URL` (new target DB)
- Backend deployment access to update `DATABASE_URL` and restart services.
- Brief write freeze window approved.

## 2) Prepare Environment Variables

```bash
export OLD_DATABASE_URL="postgres://<old_user>:<old_pass>@<old_host>:<old_port>/<old_db>"
export NEW_DATABASE_URL="postgres://<new_user>:<new_pass>@<new_host>:<new_port>/<new_db>"
export BACKUP_FILE="./prod-clone-$(date +%Y%m%d-%H%M%S).dump"
```

## 3) Freeze Writes (Brief Downtime Start)

During this step, prevent new writes by pausing webhook ingress and workers:

- Pause/disable webhook entry or scale API to zero temporarily.
- Stop background workers that write to DB (Celery worker/beat).

## 4) Run Full Clone Migration

From repo root:

```bash
./scripts/migrate_db_full_clone.sh --full --backup-file "$BACKUP_FILE"
```

Optional split execution:

```bash
./scripts/migrate_db_full_clone.sh --dump-only --backup-file "$BACKUP_FILE"
./scripts/migrate_db_full_clone.sh --restore-only --backup-file "$BACKUP_FILE"
```

## 5) Verify Data + Alembic Revision

```bash
./scripts/verify_db_migration.py --json
```

Expected:

- `"ok": true`
- table counts match for critical tables
- alembic revision matches between source and target

If verification fails, stop here and do not cut over.

## 6) Cut Over Application

1. Update backend environment:
   - `DATABASE_URL=$NEW_DATABASE_URL`
2. Restart API and worker services.
3. Run quick checks:

```bash
curl -sS http://localhost:8000/health
```

4. Run one WhatsApp smoke test message and confirm:
   - webhook returns 200
   - no DB errors in logs

## 7) Rollback Plan (If Any Issue)

If errors/regressions appear after cutover:

1. Set `DATABASE_URL` back to old production URL.
2. Restart API and workers.
3. Re-run health + WhatsApp smoke test.
4. Investigate target DB issues before retrying migration.

Rollback target time: under 5 minutes.

## 8) Post-Cutover Hardening

After stable operation:

- Lock down external DB access as planned.
- Move backend to internal DB endpoint.
- Keep backup dump file until post-cutover confidence window is complete.

