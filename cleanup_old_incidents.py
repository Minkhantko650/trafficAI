"""
Resolve all active incidents that have no tomtom_id (pre-migration rows).
The next sync will re-insert only what TomTom is currently reporting with proper IDs.
"""
import psycopg2

conn = psycopg2.connect('postgresql://postgres:MKss2026KkOCT1013@localhost:5432/trafficpredictor')
conn.autocommit = True
cur = conn.cursor()

cur.execute("SELECT COUNT(*) FROM incidents WHERE status='active' AND tomtom_id IS NULL")
count = cur.fetchone()[0]
print(f"Found {count} old active incidents with no tomtom_id")

cur.execute("UPDATE incidents SET status='resolved' WHERE status='active' AND tomtom_id IS NULL")
print(f"Resolved {cur.rowcount} stale incidents")

cur.execute("SELECT COUNT(*) FROM incidents WHERE status='active'")
print(f"Remaining active incidents: {cur.fetchone()[0]}")

conn.close()
print("Done.")
