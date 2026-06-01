"""
Skrypt do aktualizacji statusów meczów, które się już odbyły.

Oznacza mecze jako 'expired' jeśli:
- status='upcoming'
- start_time_normalized < NOW() - grace_period (domyślnie 3h)

Grace period pozwala na opóźnienia w rozpoczęciu meczu.
"""

import argparse
import logging
import psycopg2
from datetime import datetime, timedelta

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

PG_DSN = "postgresql://betting:betting_local_password@timescaledb:5432/betting"


def expire_old_matches(grace_hours: int = 3, dry_run: bool = False) -> int:
    """
    Oznacza mecze jako 'expired' jeśli czas startu minął.
    
    Args:
        grace_hours: Ile godzin po czasie startu czekać przed oznaczeniem jako expired
        dry_run: Jeśli True, tylko wyświetla co by zrobił
        
    Returns:
        Liczba zaktualizowanych meczów
    """
    conn = psycopg2.connect(PG_DSN)
    cur = conn.cursor()
    
    try:
        # Znajdź mecze, które powinny być oznaczone jako expired
        cutoff_time = datetime.utcnow() - timedelta(hours=grace_hours)
        cutoff_iso = cutoff_time.isoformat() + "+00:00"
        
        # Sprawdź ile meczów spełnia kryteria
        cur.execute("""
            SELECT COUNT(*) 
            FROM canonical_matches 
            WHERE status = 'upcoming' 
            AND start_time_normalized::timestamp < %s::timestamp
        """, (cutoff_iso,))
        
        count = cur.fetchone()[0]
        log.info(f"Znaleziono {count} meczów do oznaczenia jako 'expired' (cutoff: {cutoff_iso})")
        
        if count == 0:
            return 0
        
        # Wyświetl przykładowe mecze
        cur.execute("""
            SELECT id, team_a_name, team_b_name, start_time_normalized
            FROM canonical_matches 
            WHERE status = 'upcoming' 
            AND start_time_normalized::timestamp < %s::timestamp
            ORDER BY start_time_normalized::timestamp DESC
            LIMIT 10
        """, (cutoff_iso,))
        
        log.info("Przykładowe mecze do oznaczenia:")
        for row in cur.fetchall():
            log.info(f"  ID={row[0]}: {row[1]} vs {row[2]} ({row[3]})")
        
        if dry_run:
            log.info("DRY RUN - nie wprowadzam zmian")
            return count
        
        # Aktualizuj status
        cur.execute("""
            UPDATE canonical_matches 
            SET status = 'expired'
            WHERE status = 'upcoming' 
            AND start_time_normalized::timestamp < %s::timestamp
        """, (cutoff_iso,))
        
        updated = cur.rowcount
        conn.commit()
        
        log.info(f"Zaktualizowano {updated} meczów: status='upcoming' → 'expired'")
        
        # Wyczyść powiązane dane (opcjonalnie - można zostawić dla historii)
        # Na razie nie usuwamy, bo mogą być potrzebne do analizy CLV
        
        return updated
        
    except Exception as e:
        conn.rollback()
        log.error(f"Błąd: {e}")
        raise
    finally:
        cur.close()
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Oznacz przeterminowane mecze jako expired")
    parser.add_argument(
        "--grace-hours",
        type=int,
        default=3,
        help="Ile godzin po czasie startu czekać przed oznaczeniem jako expired (domyślnie 3)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Tylko wyświetl co by zrobił, nie wprowadzaj zmian"
    )
    
    args = parser.parse_args()
    
    updated = expire_old_matches(
        grace_hours=args.grace_hours,
        dry_run=args.dry_run
    )
    
    log.info(f"Zakończono. Zaktualizowano {updated} meczów.")


if __name__ == "__main__":
    main()
