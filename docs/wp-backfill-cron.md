# Wellness Project backfill — hourly cron

An hourly cron entry POSTs the backfill endpoint so empty Wellness Project
strength workouts get filled from Speediance without anyone clicking. Confident
matches are applied; sessions with no usable Speediance data are reported as
`skipped`; ambiguous matches are `flagged`.

It hits the app on the **loopback port (127.0.0.1:5001) directly**, which is
behind nginx's basic-auth on the public side but open on loopback — so **no
password lives in the crontab**. `flock` makes overlapping runs a no-op, and
each run logs a timestamp + the JSON result.

    # installed in root's crontab (crontab -l) — runs at :15 every hour
    15 * * * * ( date -Is; flock -n /tmp/wp-backfill.lock curl -sS --max-time 600 \
      -X POST 'http://127.0.0.1:5001/wp/backfill?mode=scheduled'; echo ) \
      >> /var/log/wp-backfill.log 2>&1

**Log:** `/var/log/wp-backfill.log` — one timestamped block per run, e.g.
`{"connected": true, "applied": [...], "skipped": [...], "flagged": [...], "errors": [...]}`.
Most hours apply nothing (everything already filled) — that's expected and cheap.

**One-time setup:** open Settings → **Wellness Project** → **Connect** to
authorize. After that the app refreshes its own token; you only reconnect if a
run reports `connect_required` (visible in the log or the Settings panel).

**To change the frequency:** `crontab -e` and edit the `15 * * * *` schedule
(e.g. `15 */2 * * *` for every 2 hours). **To disable:** comment out or delete
that line.
