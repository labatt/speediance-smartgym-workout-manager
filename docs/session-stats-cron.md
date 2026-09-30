# Personal-best cache — weekly reconcile

The dashboard's personal bests are computed from a local cache of each session's
per-exercise numbers (`session_exercise_stats` / `session_stats_scanned` in the
shared SQLite). A weekly cron keeps that cache in line with Speediance.

## Why it exists

Speediance's per-movement stat feed (`userActionStatPage`) buckets by **week** —
every `dayStr` is the Monday of a Sunday-to-Saturday week — so it cannot say what
a single day held. The only true daily source is each session's own detail, and
deriving that on every dashboard load cost ~15 API calls and about 3 seconds,
while bounding records to whatever window we were willing to pay for.

Caching the derivation makes a load ~1 call, and makes volume records **all-time**
instead of "best in the last 30 days".

## What the weekly run does

* fetches detail for any session not yet cached (oldest first, bounded per run)
* drops cached sessions Speediance no longer lists — a workout deleted in the app
  must stop setting personal bests
* re-derives everything if `DERIVED_VERSION` in `session_stats_store.py` was bumped
* marks permanently unreadable sessions so they are never retried again
  (Speediance refuses detail for a session whose custom template was later deleted —
  "Template has been deleted" — which no amount of asking will fix)

Every dashboard load also tops up the **last 10 days** (up to 5 sessions), so a
session finished minutes ago counts immediately. The weekly run is what catches
deletions and fills any gap that top-up missed.

## The cron entry

Same shape as the Wellness Project backfill: loopback only, so **no password lives
in the crontab**; `flock` makes overlapping runs a no-op; each run logs a timestamp
and the JSON report.

    # installed in root's crontab (crontab -l) — Sundays at 04:20
    20 4 * * 0 ( date -Is; flock -n /tmp/session-stats.lock curl -sS --max-time 900 \
      -X POST 'http://127.0.0.1:5001/api/session-stats/reconcile?mode=scheduled'; echo ) \
      >> /var/log/session-stats.log 2>&1

**Log:** `/var/log/session-stats.log`. A healthy run reads
`"sessionsAdded": 0, "sessionsDropped": 0, "upToDate": true` — most weeks there is
nothing to do, which is the point.

## Checking it by hand

    curl -s http://127.0.0.1:5001/api/session-stats            # what the cache holds
    curl -s -X POST http://127.0.0.1:5001/api/session-stats/reconcile   # run it now

`?days=N` bounds the window (default 400, i.e. the whole account). `?max=N` bounds
how many session details one run may fetch (default 40) — a first backfill resumes
across runs rather than making one enormous burst.

**Deletes are only honoured inside the window asked about.** A session outside the
range is absent from the response because it was not requested, not because it was
deleted; judging otherwise would wipe the cache on any narrow read.

## After changing the derivation

If you change how volume or max weight is computed (`session_stats.reduce_exercises`
or `dashboard._set_load`), **bump `DERIVED_VERSION`**. Rows stamped with an older
version are ignored and re-derived; without the bump, numbers produced by the old,
corrected-since logic would survive indefinitely.
