import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { fetchMatches, updateMatchBestOf, fetchBookmakers } from '../api/client';
import type { MatchBoardItem, BookmakerStatus } from '../types';
import './MatchList.css';

export default function MatchList() {
  const [matches, setMatches] = useState<MatchBoardItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingBoMatchId, setEditingBoMatchId] = useState<number | null>(null);
  const [savingBo, setSavingBo] = useState(false);
  const [bookmakers, setBookmakers] = useState<BookmakerStatus[]>([]);
  const [selectedBookmaker, setSelectedBookmaker] = useState<string>('');

  useEffect(() => {
    fetchBookmakers().then(setBookmakers).catch(() => {});
  }, []);

  useEffect(() => {
    fetchMatches(1, 14, selectedBookmaker || undefined)
      .then((data) => {
        setMatches(data.matches);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message);
        setLoading(false);
      });
  }, [selectedBookmaker]);

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

      <div className="filters-bar">
        <label className="filter-label">
          Bukmacher:
          <select
            value={selectedBookmaker}
            onChange={(e) => {
              setSelectedBookmaker(e.target.value);
              setLoading(true);
            }}
            className="filter-select"
          >
            <option value="">Wszyscy</option>
            {bookmakers.map((bk) => (
              <option key={bk.id} value={bk.name}>
                {bk.name}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="matches-grid">
        {matches.map((m) => {
          const hasRecommendation = Boolean(
            m.recommended_side && m.recommended_ev && m.recommended_ev > 0
          );
          const unmappedTeams = [
            !m.team_a_golgg_name ? m.team_a_name : null,
            !m.team_b_golgg_name ? m.team_b_name : null,
          ].filter(Boolean).join(', ');

          const cardClass = `match-card${hasRecommendation ? ' ev-highlight' : ''}${m.has_unmapped_teams ? ' mapping-warning' : ''}`;

          return (
            <Link
              key={m.canonical_match_id}
              to={`/matches/${m.canonical_match_id}`}
              className={cardClass}
            >
              <div className="match-header">
                <span className="league">{m.league || 'Nieznana liga'}</span>
                {m.match_confidence !== null && m.match_confidence < 1.0 && (
                  <span className="confidence-badge" title={`Pewność mapowania: ${(m.match_confidence * 100).toFixed(0)}%`}>
                    🎯 {(m.match_confidence * 100).toFixed(0)}%
                  </span>
                )}
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
                  </div>
                </div>
              </div>
              {m.recommended_side && m.recommended_ev && m.recommended_ev > 0 ? (
                <div className="match-recommendation-bar">
                  <span className="rec-badge">🎯 Typ</span>
                  <span className="rec-team">{m.recommended_team}</span>
                  {m.recommended_odds && <span className="rec-odds">@{m.recommended_odds.toFixed(2)}</span>}
                  {m.recommended_bookmaker && <span className="rec-bm">w {m.recommended_bookmaker}</span>}
                  <span className="rec-ev">EV +{(m.recommended_ev * 100).toFixed(1)}%</span>
                </div>
              ) : null}

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
