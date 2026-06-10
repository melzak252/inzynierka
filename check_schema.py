import os
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://admin:admin@localhost:5432/betting_db")
if "postgresql+psycopg2://" in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("postgresql+psycopg2://", "postgresql://")

def check_schema():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    print("--- canonical_matches columns ---")
    cur.execute("""
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_name = 'canonical_matches'
    """)
    for row in cur.fetchall():
        print(f"{row['column_name']}: {row['data_type']}")
        
    print("\n--- Sample finished matches ---")
    cur.execute("""
        SELECT id, status, winner_name, winner_side, start_time_normalized
        FROM canonical_matches
        WHERE status IN ('finished', 'completed')
        LIMIT 5
    """)
    for row in cur.fetchall():
        print(row)

    cur.close()
    conn.close()

if __name__ == "__main__":
    check_schema()
