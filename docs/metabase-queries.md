# Metabase Unified Dashboard — SQL Queries

SQL queries for manual Metabase dashboard setup. Each query is a saved question/card in Metabase.

## Panel 1: Notification Performance (Last 7 Days)

```sql
SELECT theme, mode,
  COUNT(*) as total,
  COUNT(CASE WHEN delivery_status = 'sent' THEN 1 END) as sent,
  COUNT(CASE WHEN delivery_status = 'delivered' THEN 1 END) as delivered,
  COUNT(ne.id) FILTER (WHERE ne.event_type = 'opened') as opened,
  COUNT(ne.id) FILTER (WHERE ne.event_type = 'clicked') as clicked
FROM notifications n
LEFT JOIN notification_events ne ON n.id = ne.notification_id
WHERE n.created_at >= NOW() - INTERVAL '7 days'
GROUP BY theme, mode ORDER BY total DESC;
```

## Panel 2: User State Distribution

```sql
SELECT current_state, COUNT(*) as user_count
FROM user_journey_state
GROUP BY current_state ORDER BY user_count DESC;
```

## Panel 3: Journey Funnel (Chapter Progression)

```sql
SELECT j.name as journey, snapshot_date,
  COUNT(CASE WHEN state IN (
    'progressing_active','progressing_slow','completing','completed'
  ) THEN 1 END) as active_users,
  COUNT(CASE WHEN state IN (
    'dormant_short','dormant_long','churned'
  ) THEN 1 END) as inactive_users
FROM journey_progress_snapshots jps
JOIN journeys j ON jps.journey_id = j.id
GROUP BY j.name, snapshot_date ORDER BY snapshot_date;
```

## Panel 4: Retention Impact (Attributed Returns)

```sql
SELECT DATE(ae.app_open_timestamp) as return_date,
  COUNT(ae.id) as attributed_returns,
  AVG(ae.activities_completed_after) as avg_post_return_activities,
  COUNT(DISTINCT ae.user_id) as unique_users_returned
FROM attribution_events ae
WHERE ae.app_open_timestamp >= NOW() - INTERVAL '30 days'
GROUP BY DATE(ae.app_open_timestamp) ORDER BY return_date;
```

## Panel 5: Segment Performance

```sql
SELECT * FROM segment_performance
WHERE total_sent > 10
ORDER BY open_rate_pct DESC;
```

## Panel 6: Generated Notifications (with Segmentation)

```sql
SELECT n.id, n.user_id, n.state_at_generation, n.theme,
  n.title, n.body, n.cta,
  n.generation_method, n.mode, n.delivery_status, n.created_at,
  up.learning_reason, up.profession, up.proficiency_level,
  j.name as journey_name
FROM notifications n
LEFT JOIN user_profiles up ON n.user_id = up.user_id
LEFT JOIN journeys j ON n.journey_id = j.id
ORDER BY n.created_at DESC LIMIT 100;
```
