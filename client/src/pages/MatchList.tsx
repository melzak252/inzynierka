import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { fetchMatches, updateMatchBestOf } from '../api/client';
import type { MatchBoardItem } from '../types';
import './MatchList.css';

export default function MatchList() {
  const [matches, setMatches] = useState<MatchBoardItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingBoMatchId, setEditingBoMatchId] = useState<number | null>(null);
  const [savingBo, setSavingBo] = useState(false);

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

  // Kelly Criterion: f* = (p*b - q) / b, gdzie b = odds-1, q = 1-p
  // Używamy half-Kelly (f*/2) dla bezpieczeństwa
  const calcKelly = (prob: number | null, odds: number | null): number | null => {
    if (prob === null || odds === null || odds <= 1) return null;
    const b = odds - 1;
    const q = 1 - prob;
    const kelly = (prob * b - q) / b;
    return Math.max(0, kelly / 2); // half-Kelly, minimum 0
  };

  return (
    <div className="match-list">
      <h1>Nadchodzące mecze</h1>
      <p className="subtitle">{matches.length} meczów</p>

      <div className="matches-grid">
        {matches.map((m) => {
          const evA = m.hybrid_ev_a;
          const evB = m.hybrid_ev_b;
          const kellyA = calcKelly(m.hybrid_prob_a, m.best_odds_a);
          const kellyB = calcKelly(m.hybrid_prob_b, m.best_odds_b);
          const hasStrongEv =
            (evA !== null && evA > 0.05) || (evB !== null && evB > 0.05);
          const unmappedTeams = [
            !m.team_a_golgg_name ? m.team_a_name : null,
            !m.team_b_golgg_name ? m.team_b_name : null,
          ].filter(Boolean).join(', ');

          const cardClass = `match-card${hasStrongEv ? ' ev-highlight' : ''}${m.has_unmapped_teams ? ' mapping-warning' : ''}`;

          return (
            <Link
              key={m.canonical_match_id}
              to={`/matches/${m.canonical_match_id}`}
              className={cardClass}
            >
              <div className="match-header">
                <span className="league">{m.league || 'Nieznana liga'}</span>
                {m.has_unmapped_teams && (
                  <span className="mapping-warning-badge" title={`Brak mapowania: ${unmappedTeams}. Kliknij mecz i dodaj alias.`}>
                    ⚠️ Dodaj mapowanie
                  </span>
                )}
                {editingBoMatchId === m.canonical_match_id ? (
                  <span className="best-of-picker" onClick={(e) => e.preventDefault()}>
                    {[1, 3, 5, 7].map((bo) => (
                      <button
                        key={bo}
                        className={`bo-pill${(m.best_of || 1) === bo ? ' active' : ''}${savingBo ? ' saving' : ''}`}
                        onClick={async (e) => {
                          e.preventDefault();
                          e.stopPropagation();
                          if (savingBo || (m.best_of || 1) === bo) {
                            setEditingBoMatchId(null);
                            return;
                          }
                          setSavingBo(true);
                          try {
                            await updateMatchBestOf(m.canonical_match_id, bo);
                            setMatches(prev => prev.map(mt =>
                              mt.canonical_match_id === m.canonical_match_id
                                ? { ...mt, best_of: bo }
                                : mt
                            ));
                          } catch {
                            // silently fail
                          } finally {
                            setSavingBo(false);
                            setEditingBoMatchId(null);
                          }
                        }}
                      >
                        Bo{bo}
                      </button>
                    ))}
                  </span>
                ) : (
                  <span
                    className={`best-of-badge bo${m.best_of || 1}`}
                    onClick={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      setEditingBoMatchId(m.canonical_match_id);
                    }}
                    title="Kliknij aby zmienić"
                  >
                    Bo{m.best_of || 1}
                  </span>
                )}
                <span className="datetime">{formatDateTime(m.start_time_normalized)}</span>
              </div>

              <div className="match-teams">
                <div className="team">
                  <span className="team-name">
                    {m.team_a_name || '?'}
                    {!m.team_a_golgg_name && (
                      <span className="team-unmapped" title="Brak mapowania do GOL.GG — kliknij mecz i dodaj alias">?</span>
                    )}
                  </span>
                  <div className="odds-block">
                    {m.best_odds_a && (
                      <span className="odds">{m.best_odds_a.toFixed(2)}</span>
                    )}
                    {evA !== null && evA > 0 && (
                      <span className={`ev-value${evA > 0.05 ? ' ev-strong' : ''}`}>
                        EV {(evA * 100).toFixed(1)}%
                      </span>
                    )}
                    {kellyA !== null && kellyA > 0 && (
                      <span className={`kelly-value${kellyA > 0.05 ? ' kelly-strong' : ''}`}>
                        Kelly {(kellyA * 100).toFixed(1)}%
                      </span>
                    )}
                  </div>
                </div>
                <span className="vs">vs</span>
                <div className="team">
                  <span className="team-name">
                    {m.team_b_name || '?'}
                    {!m.team_b_golgg_name && (
                      <span className="team-unmapped" title="Brak mapowania do GOL.GG — kliknij mecz i dodaj alias">?</span>
                    )}
                  </span>
                  <div className="odds-block">
                    {m.best_odds_b && (
                      <span className="odds">{m.best_odds_b.toFixed(2)}</span>
                    )}
                    {evB !== null && evB > 0 && (
                      <span className={`ev-value${evB > 0.05 ? ' ev-strong' : ''}`}>
                        EV {(evB * 100).toFixed(1)}%
                      </span>
                    )}
                    {kellyB !== null && kellyB > 0 && (
                      <span className={`kelly-value${kellyB > 0.05 ? ' kelly-strong' : ''}`}>
                        Kelly {(kellyB * 100).toFixed(1)}%
                      </span>
                    )}
                  </div>
                </div>
              </div>

              <div className="match-footer">
                <span className="bookmakers">
                  {m.bookmaker_count} bukmacher{m.bookmaker_count !== 1 ? 'ów' : ''}
                </span>
                {m.best_bookmaker_a && m.best_bookmaker_b && m.best_bookmaker_a === m.best_bookmaker_b ? (
                  <span className="best-bookmaker" title="Najlepsze kursy na obie strony">
                    {m.best_bookmaker_a}
                  </span>
                ) : (
                  <>
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
                  </>
                )}
                {m.arb_after_tax && (
                  <span className="arb-badge">ARB</span>
                )}
                {m.has_unmapped_teams && (
                  <span className="mapping-footer-note">brak predykcji do czasu mapowania</span>
                )}
              </div>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
