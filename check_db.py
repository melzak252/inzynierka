import psycopg2
import os
import sys

DB_DSN = "postgresql://betting:betting_local_password@192.168.1.17:5432/betting"

def main():
    print("Starting DB check...")
    try:
        print(f"Connecting to {DB_DSN}...")
        conn = psycopg2.connect(DB_DSN)
        cur = conn.cursor()
        print("Connected successfully.")
        
        print("--- Model Counts ---")
        cur.execute("SELECT model_name, model_version, COUNT(*) FROM canonical_predictions GROUP BY 1, 2 ORDER BY 3 DESC")
        rows = cur.fetchall()
        if not rows:
            print("No predictions found in canonical_predictions table.")
        for row in rows:
            print(f"{row[0]} | {row[1]} | {row[2]}")
            
        print("\n--- Finished Matches with Predictions ---")
        cur.execute("""
            SELECT cp.model_name, cp.model_version, COUNT(DISTINCT cp.canonical_match_id)
            FROM canonical_predictions cp
            JOIN canonical_matches cm ON cm.id = cp.canonical_match_id
            WHERE cm.status IN ('finished', 'completed')
            GROUP BY 1, 2
        """)
        rows = cur.fetchall()
        if not rows:
            print("No finished matches with predictions found.")
        for row in rows:
            print(f"{row[0]} | {row[1]} | {row[2]}")
            
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)

if __name__ == "__main__":
    main()
