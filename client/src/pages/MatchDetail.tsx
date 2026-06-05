import { useEffect, useState, useMemo } from 'react';
import { useParams, Link } from 'react-router-dom';
import { fetchMatchDetail, fetchPredictionHistory } from '../api/client';
import type { MatchDetailResponse, PredictionHistoryPoint } from '../types';
import './MatchDetail.css';

// ─── Prediction History Chart Component ──────────────────────

interface ChartProps {
  data: PredictionHistoryPoint[];
  teamA: string;
  teamB: string;
}

function PredictionHistoryChart({ data, teamA, teamB }: ChartProps) {
  // Separate data by model
  const models = useMemo(() => {
    const map = new Map<string, PredictionHistoryPoint[]>();
    for (const pt of data) {
      const key = pt.model_name;
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(pt);
    }
    // Sort each model's points by timestamp
    for (const pts of map.values()) {
      pts.sort((a, b) => a.timestamp.localeCompare(b.timestamp));
    }
    return map;
  }, [data]);

  const modelNames = Array.from(models.keys());

  // Build unique time axis from all data points
  const timeLabels = useMemo(() => {
    const tsSet = new Set(data.map(d => d.timestamp));
    return Array.from(tsSet).sort();
  }, [data]);

  if (timeLabels.length < 2) {
    return (
      <section className="prediction-history-section">
        <h2>Historia predykcji i EV</h2>
        <p className="no-data">Za mało danych do wyświetlenia wykresu (minimum 2 punkty czasowe)</p>
      </section>
    );
  }

  // Chart dimensions
  const W = 900;
  const H = 420;
  const margin = { top: 30, right: 30, bottom: 50, left: 55 };
  const plotW = W - margin.left - margin.right;
  const plotH = H - margin.top - margin.bottom;

  // Y axis: probability 0..1
  const yMin = 0;
  const yMax = 1;
  const yScale = (v: number) => margin.top + plotH - ((v - yMin) / (yMax - yMin)) * plotH;
  const xScale = (i: number) => margin.left + (i / (timeLabels.length - 1)) * plotW;

  // Model colors
  const modelColors: Record<string, string> = {};
  const palette = ['#4fc3f7', '#ff9800', '#e040fb', '#66bb6a', '#ef5350'];
  modelNames.forEach((name, i) => {
    modelColors[name] = palette[i % palette.length];
  });

  // Market color
  const marketColor = '#888888';

  // Build SVG path for a series
  const buildPath = (points: { timeIdx: number; value: number }[]) => {
    return points
      .map((p, i) => {
        const x = xScale(p.timeIdx);
        const y = yScale(p.value);
        return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(' ');
  };

  // Build EV zone rectangles (where ev_a > 0.05 or ev_b > 0.05)
  const evZones = useMemo(() => {
    const zones: { startIdx: number; endIdx: number; side: 'a' | 'b' }[] = [];
    // For each consecutive pair of time indices, check if any model has EV > 5%
    for (let i = 0; i < timeLabels.length - 1; i++) {
      const ts = timeLabels[i];
      const tsNext = timeLabels[i + 1];
      // Check all points at this timestamp
      const pointsAtTs = data.filter(d => d.timestamp === ts);
      const pointsAtTsNext = data.filter(d => d.timestamp === tsNext);
      const hasEvA = pointsAtTs.some(p => p.ev_a != null && p.ev_a > 0.05) ||
                     pointsAtTsNext.some(p => p.ev_a != null && p.ev_a > 0.05);
      const hasEvB = pointsAtTs.some(p => p.ev_b != null && p.ev_b > 0.05) ||
                     pointsAtTsNext.some(p => p.ev_b != null && p.ev_b > 0.05);
      if (hasEvA) zones.push({ startIdx: i, endIdx: i + 1, side: 'a' });
      if (hasEvB) zones.push({ startIdx: i, endIdx: i + 1, side: 'b' });
    }
    return zones;
  }, [data, timeLabels]);

  // Y grid lines
  const yTicks = [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0];

  // Format time label
  const formatTimeLabel = (iso: string) => {
    const d = new Date(iso);
    return d.toLocaleString('pl-PL', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
  };

  // Show every Nth time label to avoid overlap
  const labelStep = Math.max(1, Math.floor(timeLabels.length / 10));

  return (
    <section className="prediction-history-section">
      <h2>Historia predykcji i EV</h2>
      <div className="chart-container">
        <svg viewBox={`0 0 ${W} ${H}`} className="pred-chart">
          {/* EV zones - green for team A EV > 5%, red for team B EV > 5% */}
          {evZones.map((zone, i) => {
            const x1 = xScale(zone.startIdx);
            const x2 = xScale(zone.endIdx);
            const fill = zone.side === 'a' ? 'rgba(76,175,80,0.12)' : 'rgba(239,83,80,0.12)';
            return (
              <rect
                key={`evzone-${i}`}
                x={x1}
                y={margin.top}
                width={x2 - x1}
                height={plotH}
                fill={fill}
              />
            );
          })}

          {/* Y grid lines */}
          {yTicks.map(v => (
            <g key={`ygrid-${v}`}>
              <line
                x1={margin.left}
                y1={yScale(v)}
                x2={W - margin.right}
                y2={yScale(v)}
                stroke="#2a2a4a"
                strokeWidth={1}
              />
              <text
                x={margin.left - 8}
                y={yScale(v) + 4}
                textAnchor="end"
                fill="#888"
                fontSize={11}
              >
                {(v * 100).toFixed(0)}%
              </text>
            </g>
          ))}

          {/* 50% reference line */}
          <line
            x1={margin.left}
            y1={yScale(0.5)}
            x2={W - margin.right}
            y2={yScale(0.5)}
            stroke="#4a4a6a"
            strokeWidth={1.5}
            strokeDasharray="6,4"
          />

          {/* Market probability line (team A) */}
          {(() => {
            const marketPoints: { timeIdx: number; value: number }[] = [];
            for (let i = 0; i < timeLabels.length; i++) {
              const pts = data.filter(d => d.timestamp === timeLabels[i] && d.market_prob_a != null);
              if (pts.length > 0) {
                const avg = pts.reduce((s, p) => s + (p.market_prob_a ?? 0), 0) / pts.length;
                marketPoints.push({ timeIdx: i, value: avg });
              }
            }
            if (marketPoints.length < 2) return null;
            return (
              <path
                d={buildPath(marketPoints)}
                fill="none"
                stroke={marketColor}
                strokeWidth={2}
                strokeDasharray="8,4"
              />
            );
          })()}

          {/* Model probability lines (team A prob_a) */}
          {modelNames.map(modelName => {
            const pts = models.get(modelName)!;
            const linePoints: { timeIdx: number; value: number }[] = [];
            for (const pt of pts) {
              const idx = timeLabels.indexOf(pt.timestamp);
              if (idx >= 0 && pt.prob_a != null) {
                linePoints.push({ timeIdx: idx, value: pt.prob_a });
              }
            }
            if (linePoints.length < 2) return null;
            return (
              <path
                key={`model-${modelName}`}
                d={buildPath(linePoints)}
                fill="none"
                stroke={modelColors[modelName]}
                strokeWidth={2.5}
              />
            );
          })}

          {/* Data points for model lines */}
          {modelNames.map(modelName => {
            const pts = models.get(modelName)!;
            const dots: { x: number; y: number; evA: number | null }[] = [];
            for (const pt of pts) {
              const idx = timeLabels.indexOf(pt.timestamp);
              if (idx >= 0 && pt.prob_a != null) {
                dots.push({
                  x: xScale(idx),
                  y: yScale(pt.prob_a),
                  evA: pt.ev_a,
                });
              }
            }
            return dots.map((d, i) => (
              <circle
                key={`dot-${modelName}-${i}`}
                cx={d.x}
                cy={d.y}
                r={d.evA != null && d.evA > 0.05 ? 4 : 2.5}
                fill={modelColors[modelName]}
                stroke={d.evA != null && d.evA > 0.05 ? '#4caf50' : 'none'}
                strokeWidth={d.evA != null && d.evA > 0.05 ? 2 : 0}
              />
            ));
          })}

          {/* Data points for market line */}
          {(() => {
            const dots: { x: number; y: number }[] = [];
            for (let i = 0; i < timeLabels.length; i++) {
              const pts = data.filter(d => d.timestamp === timeLabels[i] && d.market_prob_a != null);
              if (pts.length > 0) {
                const avg = pts.reduce((s, p) => s + (p.market_prob_a ?? 0), 0) / pts.length;
                dots.push({ x: xScale(i), y: yScale(avg) });
              }
            }
            return dots.map((d, i) => (
              <circle
                key={`market-dot-${i}`}
                cx={d.x}
                cy={d.y}
                r={2}
                fill={marketColor}
              />
            ));
          })()}

          {/* X axis labels */}
          {timeLabels.map((ts, i) => {
            if (i % labelStep !== 0 && i !== timeLabels.length - 1) return null;
            return (
              <text
                key={`xlabel-${i}`}
                x={xScale(i)}
                y={H - margin.bottom + 20}
                textAnchor="middle"
                fill="#888"
                fontSize={10}
              >
                {formatTimeLabel(ts)}
              </text>
            );
          })}

          {/* Axis labels */}
          <text
            x={margin.left - 40}
            y={margin.top + plotH / 2}
            textAnchor="middle"
            fill="#aaa"
            fontSize={12}
            transform={`rotate(-90, ${margin.left - 40}, ${margin.top + plotH / 2})`}
          >
            Prawdopodobieństwo ({teamA})
          </text>
        </svg>

        {/* Legend */}
        <div className="chart-legend">
          {modelNames.map(name => (
            <span key={name} className="legend-item">
              <span
                className="legend-line"
                style={{ backgroundColor: modelColors[name] }}
              />
              {name}
            </span>
          ))}
          <span className="legend-item">
            <span className="legend-line legend-dashed" style={{ backgroundColor: marketColor }} />
            Rynek (średnia)
          </span>
          <span className="legend-item">
            <span className="legend-ev ev-positive" />
            EV {teamA} &gt; 5%
          </span>
          <span className="legend-item">
            <span className="legend-ev ev-negative" />
            EV {teamB} &gt; 5%
          </span>
        </div>
      </div>
    </section>
  );
}

// ─── Match Detail Page ──────────────────────────────────────

export default function MatchDetail() {
  const { id } = useParams<{ id: string }>();
  const [match, setMatch] = useState<MatchDetailResponse | null>(null);
  const [predHistory, setPredHistory] = useState<PredictionHistoryPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    Promise.all([
      fetchMatchDetail(parseInt(id)),
      fetchPredictionHistory(parseInt(id)),
    ])
      .then(([matchData, historyData]) => {
        setMatch(matchData);
        setPredHistory(historyData);
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
              <span>EV A</span>
              <span>Kelly A</span>
              <span>{match.team_b_name}</span>
              <span>EV B</span>
              <span>Kelly B</span>
              <span>Aktualizacja</span>
              <span>Link</span>
            </div>
            {match.odds.map((odd, idx) => (
              <div key={idx} className="odds-row">
                <span className="bookmaker-name">{odd.bookmaker}</span>
                <span className="odds-value">
                  {odd.canonical_odds_a ? odd.canonical_odds_a.toFixed(2) : '—'}
                </span>
                <span className={`ev-value ${odd.ev_a && odd.ev_a > 0 ? 'positive' : ''}`}>
                  {odd.ev_a ? `${(odd.ev_a * 100).toFixed(1)}%` : '—'}
                </span>
                <span className={`kelly-value ${odd.kelly_a && odd.kelly_a > 0 ? 'positive' : ''}`}>
                  {odd.kelly_a ? `${(odd.kelly_a * 100).toFixed(1)}%` : '—'}
                </span>
                <span className="odds-value">
                  {odd.canonical_odds_b ? odd.canonical_odds_b.toFixed(2) : '—'}
                </span>
                <span className={`ev-value ${odd.ev_b && odd.ev_b > 0 ? 'positive' : ''}`}>
                  {odd.ev_b ? `${(odd.ev_b * 100).toFixed(1)}%` : '—'}
                </span>
                <span className={`kelly-value ${odd.kelly_b && odd.kelly_b > 0 ? 'positive' : ''}`}>
                  {odd.kelly_b ? `${(odd.kelly_b * 100).toFixed(1)}%` : '—'}
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
              <span>Kelly A</span>
              <span>Kelly B</span>
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
                <span className={`kelly-value ${pred.kelly_a && pred.kelly_a > 0 ? 'positive' : ''}`}>
                  {pred.kelly_a ? `${(pred.kelly_a * 100).toFixed(1)}%` : '—'}
                </span>
                <span className={`kelly-value ${pred.kelly_b && pred.kelly_b > 0 ? 'positive' : ''}`}>
                  {pred.kelly_b ? `${(pred.kelly_b * 100).toFixed(1)}%` : '—'}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      {predHistory.length > 0 && (
        <PredictionHistoryChart
          data={predHistory}
          teamA={match.team_a_name || 'A'}
          teamB={match.team_b_name || 'B'}
        />
      )}

      {match.team_comparison && (
        <section className="comparison-section">
          <h2>Porównanie drużyn</h2>
          <div className="comparison-table">
            <div className="comparison-header">
              <span></span>
              <span>{match.team_a_name}</span>
              <span>{match.team_b_name}</span>
            </div>
            <div className="comparison-row">
              <span className="comparison-label">Nazwa kanoniczna</span>
              <span>{match.team_comparison.team_a?.canonical_name || '—'}</span>
              <span>{match.team_comparison.team_b?.canonical_name || '—'}</span>
            </div>
            <div className="comparison-row">
              <span className="comparison-label">Nazwa gol.gg</span>
              <span>{match.team_comparison.team_a?.golgg_name || '—'}</span>
              <span>{match.team_comparison.team_b?.golgg_name || '—'}</span>
            </div>
            <div className="comparison-row">
              <span className="comparison-label">Pewność mapowania</span>
              <span>
                {match.team_comparison.team_a?.confidence
                  ? `${(match.team_comparison.team_a.confidence * 100).toFixed(0)}%`
                  : '—'}
              </span>
              <span>
                {match.team_comparison.team_b?.confidence
                  ? `${(match.team_comparison.team_b.confidence * 100).toFixed(0)}%`
                  : '—'}
              </span>
            </div>
            <div className="comparison-row">
              <span className="comparison-label">
                Rating {match.team_comparison.rating_system || ''}
              </span>
              <span className={`rating-value ${
                match.team_comparison.team_a_rating && match.team_comparison.team_b_rating
                  ? match.team_comparison.team_a_rating > match.team_comparison.team_b_rating
                    ? 'rating-higher' : 'rating-lower'
                  : ''
              }`}>
                {match.team_comparison.team_a_rating
                  ? match.team_comparison.team_a_rating.toFixed(1)
                  : '—'}
              </span>
              <span className={`rating-value ${
                match.team_comparison.team_a_rating && match.team_comparison.team_b_rating
                  ? match.team_comparison.team_b_rating > match.team_comparison.team_a_rating
                    ? 'rating-higher' : 'rating-lower'
                  : ''
              }`}>
                {match.team_comparison.team_b_rating
                  ? match.team_comparison.team_b_rating.toFixed(1)
                  : '—'}
              </span>
            </div>
            {match.team_comparison.team_a_rating && match.team_comparison.team_b_rating && (
              <div className="comparison-row">
                <span className="comparison-label">Różnica ratingów</span>
                <td className="rating-diff" colSpan={2}>
                  {(match.team_comparison.team_a_rating - match.team_comparison.team_b_rating) > 0 ? '+' : ''}
                  {(match.team_comparison.team_a_rating - match.team_comparison.team_b_rating).toFixed(1)}
                </td>
              </div>
            )}
          </div>
        </section>
      )}
    </div>
  );
}
