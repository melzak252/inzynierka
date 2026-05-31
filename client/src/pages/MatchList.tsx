import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { fetchMatches } from '../api/client';
import type { MatchBoardItem } from '../types';
import './MatchList.css';

export default function MatchList() {
  const [matches, setMatches] = useState<MatchBoardItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchMatches()
      .then((data) => {
        setMatches(data.matches);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message);
        setLoading(false);
      });
  }, []);

  if (loading) {
    return <div className="loading">Ładowanie meczów...</div>;
  }

  if (error) {
    return <div className="error">Błąd: {error}</div>;
  }

  if (matches.length === 0) {
    return <div className="empty">Brak nadchodzących meczów</div>;
  }

  const formatDateTime = (iso: string | null) => {
    if (!iso) return '—';
    const d = new Date(iso);
    return d.toLocaleString('pl-PL', {
      day: '2-digit',
      month: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  return (
    <div className="match-list">
      <h1>Nadchodzące mecze</h1>
      <p className="subtitle">{matches.length} meczów</p>

      <div className="matches-grid">
        {matches.map((m) => {
          const evA = m.hybrid_ev_a;
          const evB = m.hybrid_ev_b;
          const hasStrongEv =
            (evA !== null && evA > 0.05) || (evB !== null && evB > 0.05);

          const cardClass = `match-card${hasStrongEv ? ' ev-highlight' : ''}`;

          return (
            <Link
              key={m.canonical_match_id}
              to={`/matches/${m.canonical_match_id}`}
              className={cardClass}
            >
              <div className="match-header">
                <span className="league">{m.league || 'Nieznana liga'}</span>
                <span className="datetime">{formatDateTime(m.start_time_normalized)}</span>
              </div>

              <div className="match-teams">
                <div className="team">
                  <span className="team-name">{m.team_a_name || '?'}</span>
                  <div className="odds-block">
                    {m.best_odds_a && (
                      <span className="odds">{m.best_odds_a.toFixed(2)}</span>
                    )}
                    {evA !== null && evA > 0 && (
                      <span className={`ev-value${evA > 0.05 ? ' ev-strong' : ''}`}>
                        EV {(evA * 100).toFixed(1)}%
                      </span>
                    )}
                  </div>
                </div>
                <span className="vs">vs</span>
                <div className="team">
                  <span className="team-name">{m.team_b_name || '?'}</span>
                  <div className="odds-block">
                    {m.best_odds_b && (
                      <span className="odds">{m.best_odds_b.toFixed(2)}</span>
                    )}
                    {evB !== null && evB > 0 && (
                      <span className={`ev-value${evB > 0.05 ? ' ev-strong' : ''}`}>
                        EV {(evB * 100).toFixed(1)}%
                      </span>
                    )}
                  </div>
                </div>
              </div>

              <div className="match-footer">
                <span className="bookmakers">
                  {m.bookmaker_count} bukmacher{m.bookmaker_count !== 1 ? 'ów' : ''}
                </span>
                {m.best_bookmaker_a && (
                  <span className="best-bookmaker" title="Najlepszy kurs na {m.team_a_name}">
                    {m.best_bookmaker_a}
                  </span>
                )}
                {m.best_bookmaker_b && (
                  <span className="best-bookmaker" title="Najlepszy kurs na {m.team_b_name}">
                    {m.best_bookmaker_b}
                  </span>
                )}
                {m.arb_after_tax && (
                  <span className="arb-badge">ARB</span>
                )}
              </div>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
