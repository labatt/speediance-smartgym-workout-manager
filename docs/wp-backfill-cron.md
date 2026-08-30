# Wellness Project backfill — daily cron

The scheduled scan is a plain cron entry that POSTs the backfill endpoint. It
reuses the site's nginx basic-auth credentials. Confident matches are applied
automatically; ambiguous ones are recorded and shown on /wp/reconcile.

    # crontab -e  (runs 06:15 daily)
    15 6 * * * curl -sS -u labatt:<basic-auth-pw> -X POST \
      'https://speediance.labattsimon.com/wp/backfill?mode=scheduled' \
      >> /var/log/wp-backfill.log 2>&1

One-time setup: open https://speediance.labattsimon.com/wp/reconcile and click
**Connect Wellness Project** to authorize. After that the app refreshes its own
token; re-connect only if a run reports `connect_required`.
