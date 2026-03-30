"""One-time migration: add tomtom_id column to incidents table."""
import psycopg2

conn = psycopg2.connect('postgresql://postgres:MKss2026KkOCT1013@localhost:5432/trafficpredictor')
conn.autocommit = True
cur = conn.cursor()

cur.execute("ALTER TABLE incidents ADD COLUMN IF NOT EXISTS tomtom_id VARCHAR(255)")
print("ALTER TABLE done")

cur.execute("CREATE INDEX IF NOT EXISTS ix_incidents_tomtom_id ON incidents(tomtom_id)")
print("INDEX done")

cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='incidents' AND column_name='tomtom_id'")
exists = cur.fetchone()
print(f"tomtom_id column exists: {exists is not None}")

cur.execute("SELECT COUNT(*) FROM incidents WHERE status='active' AND location_en IS NULL")
print(f"Still missing location_en: {cur.fetchone()[0]}")

cur.execute("SELECT COUNT(*) FROM incidents WHERE status='active'")
print(f"Total active incidents: {cur.fetchone()[0]}")

conn.close()
print("Migration complete.")
