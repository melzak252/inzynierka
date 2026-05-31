import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { fetchMatchDetail } from '../api/client';
import type { MatchDetailResponse } from '../types';
import './MatchDetail.css';

export default function MatchDetail() {
  const { id } = useParams<{ id: string }>();
  const [match, setMatch] = useState<MatchDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    fetchMatchDetail(parseInt(id))
      .then((data) => {
        setMatch(data);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message);
        setLoading(false);
      });
  }, [id]);

  if (loading) {
    return <div className="loading">Ładowanie szczegółów meczu...</div>;
  }

  if (error) {
    return <div className="error">Błąd: {error}</div>;
  }

  if (!match) {
    return <div className="empty">Nie znaleziono meczu</div>;
  }

  const formatDateTime = (iso: string | null) => {
    if (!iso) return '—';
    const d = new Date(iso);
    return d.toLocaleString('pl-PL', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const formatScrapedAt = (iso: string | null) => {
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
    <div className="match-detail">
      <Link to="/" className="back-link">
        ← Powrót do listy meczów
      </Link>

      <div className="match-header-card">
        <div className="league-info">
          <span className="league">{match.league || 'Nieznana liga'}</span>
          <span className="status">{match.status}</span>
        </div>
        <h1>
          {match.team_a_name || '?'} vs {match.team_b_name || '?'}
        </h1>
        <div className="datetime">{formatDateTime(match.start_time_normalized)}</div>
      </div>

      <section className="odds-section">
        <h2>Kursy bukmacherów</h2>
        {match.odds.length === 0 ? (
          <p className="no-data">Brak dostępnych kursów</p>
        ) : (
          <div className="odds-table">
            <div className="odds-header">
              <span>Bukmacher</span>
              <span>{match.team_a_name}</span>
              <span>{match.team_b_name}</span>
              <span>Aktualizacja</span>
              <span>Link</span>
            </div>
            {match.odds.map((odd, idx) => (
              <div key={idx} className="odds-row">
                <span className="bookmaker-name">{odd.bookmaker}</span>
                <span className="odds-value">
                  {odd.canonical_odds_a ? odd.canonical_odds_a.toFixed(2) : '—'}
                </span>
                <span className="odds-value">
                  {odd.canonical_odds_b ? odd.canonical_odds_b.toFixed(2) : '—'}
                </span>
                <span className="scraped-at">{formatScrapedAt(odd.scraped_at)}</span>
                <span className="link-cell">
                  {odd.offer_url && (
                    <a href={odd.offer_url} target="_blank" rel="noopener noreferrer">
                      Oferta →
                    </a>
                  )}
                </span>
              </div>
            ))}
          </div>
        )}
      </section>

      {match.predictions.length > 0 && (
        <section className="predictions-section">
          <h2>Predykcje modeli</h2>
          <div className="predictions-table">
            <div className="predictions-header">
              <span>Model</span>
              <span>Prawd. A</span>
              <span>Prawd. B</span>
              <span>EV A</span>
              <span>EV B</span>
            </div>
            {match.predictions.map((pred, idx) => (
              <div key={idx} className="predictions-row">
                <span className="model-name">
                  {pred.model_name} <small>({pred.model_version})</small>
                </span>
                <span className="prob-value">
                  {pred.prob_a ? `${(pred.prob_a * 100).toFixed(1)}%` : '—'}
                </span>
                <span className="prob-value">
                  {pred.prob_b ? `${(pred.prob_b * 100).toFixed(1)}%` : '—'}
                </span>
                <span className={`ev-value ${pred.ev_a && pred.ev_a > 0 ? 'positive' : ''}`}>
                  {pred.ev_a ? `${(pred.ev_a * 100).toFixed(1)}%` : '—'}
                </span>
                <span className={`ev-value ${pred.ev_b && pred.ev_b > 0 ? 'positive' : ''}`}>
                  {pred.ev_b ? `${(pred.ev_b * 100).toFixed(1)}%` : '—'}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
