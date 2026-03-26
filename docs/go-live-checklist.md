# Go-Live Checklist: Shadow → Live Mode

Steps to switch from shadow mode to live notification delivery.

## Pre-Launch Verification

- [ ] Review shadow notifications in Metabase dashboard (Panel 6) — verify quality, Hinglish naturalness, story references
- [ ] Review shadow notifications via admin API: `GET /admin/notifications/shadow-review` — spot-check 50+ notifications
- [ ] Verify all CleverTap campaign shells configured (one per notification theme)
- [ ] Set CleverTap credentials in production env vars: `CLEVERTAP_ACCOUNT_ID`, `CLEVERTAP_PASSCODE`
- [ ] Run full test suite: `pytest tests/ -v` — zero failures
- [ ] Verify all services healthy: `curl /admin/health` — status: "healthy"
- [ ] Confirm frequency cap is set correctly: `GET /admin/config?category=notification` — verify `notification.max_daily=6`
- [ ] Confirm notification time windows are correct (IST slots 1-5)

## Go Live

- [ ] Update mode: `PUT /admin/config/notification.mode` with body `{"value": "live"}`
- [ ] Verify mode change: `GET /admin/config?category=notification` — confirm `notification.mode=live`
- [ ] Send test notification manually to internal user (verify CleverTap delivery end-to-end)

## Post-Launch Monitoring (First 24h)

- [ ] Check Metabase Panel 1: Notification Performance — verify delivery rates
- [ ] Check Flower dashboard (port 5555): verify workers processing tasks
- [ ] Monitor app logs: `docker compose logs -f app worker` — check for errors
- [ ] Verify CleverTap sync is running: check Metabase for opened/clicked events appearing
- [ ] Check attribution events: verify app returns being attributed to notifications

## Rollback (If Needed)

- [ ] Switch back to shadow: `PUT /admin/config/notification.mode` with body `{"value": "shadow"}`
- [ ] Verify mode change took effect
- [ ] Investigate issues in logs and Metabase before retrying
