import { useEffect, useState, useMemo } from 'react';
import { useParams, Link } from 'react-router-dom';
import { fetchMatchDetail, fetchPredictionHistory, updateMatchBestOf, predictMatch, createTeamAlias, deleteTeamAlias, unblockTeamAlias, searchGolggTeams } from '../api/client';
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

  // Build unique time axis from all data points, bucketed by minute
  const timeLabels = useMemo(() => {
    const tsSet = new Set(data.map(d => d.timestamp));
    return Array.from(tsSet).sort();
  }, [data]);

  // Compute dynamic Y range from actual data
  const { yMin, yMax, yTicks } = useMemo(() => {
    const allProbs: number[] = [];
    for (const pt of data) {
      if (pt.prob_a != null) allProbs.push(pt.prob_a);
      if (pt.prob_b != null) allProbs.push(pt.prob_b);
      if (pt.market_prob_a != null) allProbs.push(pt.market_prob_a);
      if (pt.market_prob_b != null) allProbs.push(pt.market_prob_b);
    }
    if (allProbs.length === 0) {
      return { yMin: 0, yMax: 1, yTicks: [0, 0.25, 0.5, 0.75, 1] };
    }
    const dataMin = Math.min(...allProbs);
    const dataMax = Math.max(...allProbs);
    // Add 5% padding on each side, but ensure at least 10% range
    const range = dataMax - dataMin;
    const padding = Math.max(range * 0.15, 0.05);
    let lo = Math.max(0, dataMin - padding);
    let hi = Math.min(1, dataMax + padding);
    // Ensure minimum 10% visible range
    if (hi - lo < 0.10) {
      const center = (lo + hi) / 2;
      lo = Math.max(0, center - 0.05);
      hi = Math.min(1, center + 0.05);
    }
    // Round to nice tick values (every 5% or 10%)
    const tickStep = (hi - lo) > 0.4 ? 0.10 : (hi - lo) > 0.2 ? 0.05 : 0.02;
    const niceLo = Math.floor(lo / tickStep) * tickStep;
    const niceHi = Math.ceil(hi / tickStep) * tickStep;
    const ticks: number[] = [];
    for (let v = niceLo; v <= niceHi + tickStep * 0.01; v += tickStep) {
      ticks.push(Math.round(v * 1000) / 1000);
    }
    return { yMin: niceLo, yMax: niceHi, yTicks: ticks };
  }, [data]);

  // Compute EV+ stats for the info table
  const evStats = useMemo(() => {
    const evPlusPoints = data.filter(
      pt => (pt.ev_a != null && pt.ev_a > 0) || (pt.ev_b != null && pt.ev_b > 0)
    );

    // Min/max prob_a and prob_b across all data points
    const probAs = data.filter(pt => pt.prob_a != null).map(pt => ({ value: pt.prob_a!, ts: pt.timestamp, model: pt.model_name }));
    const probBs = data.filter(pt => pt.prob_b != null).map(pt => ({ value: pt.prob_b!, ts: pt.timestamp, model: pt.model_name }));

    const minProbA = probAs.length > 0 ? probAs.reduce((a, b) => a.value < b.value ? a : b) : null;
    const maxProbA = probAs.length > 0 ? probAs.reduce((a, b) => a.value > b.value ? a : b) : null;
    const minProbB = probBs.length > 0 ? probBs.reduce((a, b) => a.value < b.value ? a : b) : null;
    const maxProbB = probBs.length > 0 ? probBs.reduce((a, b) => a.value > b.value ? a : b) : null;

    // Current (latest) values per model
    const currentByModel = new Map<string, PredictionHistoryPoint>();
    for (const pt of data) {
      const existing = currentByModel.get(pt.model_name);
      if (!existing || pt.timestamp > existing.timestamp) {
        currentByModel.set(pt.model_name, pt);
      }
    }
    const currentPoints = Array.from(currentByModel.values());

    // EV+ periods
    const evPlusA = evPlusPoints.filter(pt => pt.ev_a != null && pt.ev_a > 0);
    const evPlusB = evPlusPoints.filter(pt => pt.ev_b != null && pt.ev_b > 0);

    // Max EV seen
    const maxEvA = evPlusA.length > 0 ? evPlusA.reduce((a, b) => (a.ev_a ?? 0) > (b.ev_a ?? 0) ? a : b) : null;
    const maxEvB = evPlusB.length > 0 ? evPlusB.reduce((a, b) => (b.ev_b ?? 0) > (a.ev_b ?? 0) ? b : a) : null;

    // Market probability stats
    const marketProbsA = data.filter(pt => pt.market_prob_a != null).map(pt => ({ value: pt.market_prob_a!, ts: pt.timestamp }));
    const marketProbsB = data.filter(pt => pt.market_prob_b != null).map(pt => ({ value: pt.market_prob_b!, ts: pt.timestamp }));
    const currentMarketA = marketProbsA.length > 0 ? marketProbsA[marketProbsA.length - 1] : null;
    const currentMarketB = marketProbsB.length > 0 ? marketProbsB[marketProbsB.length - 1] : null;
    const minMarketA = marketProbsA.length > 0 ? marketProbsA.reduce((a, b) => a.value < b.value ? a : b) : null;
    const maxMarketA = marketProbsA.length > 0 ? marketProbsA.reduce((a, b) => a.value > b.value ? a : b) : null;
    const minMarketB = marketProbsB.length > 0 ? marketProbsB.reduce((a, b) => a.value < b.value ? a : b) : null;
    const maxMarketB = marketProbsB.length > 0 ? marketProbsB.reduce((a, b) => a.value > b.value ? a : b) : null;

    return {
      evPlusCount: evPlusPoints.length,
      evPlusACount: evPlusA.length,
      evPlusBCount: evPlusB.length,
      minProbA, maxProbA, minProbB, maxProbB,
      currentPoints,
      maxEvA, maxEvB,
      evPlusA, evPlusB,
      currentMarketA, currentMarketB,
      minMarketA, maxMarketA, minMarketB, maxMarketB,
    };
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
                {v >= 0.01 ? `${(v * 100).toFixed(0)}%` : `${(v * 100).toFixed(1)}%`}
              </text>
            </g>
          ))}

          {/* 50% reference line (only if within visible range) */}
          {yMin <= 0.5 && yMax >= 0.5 && (
            <line
              x1={margin.left}
              y1={yScale(0.5)}
              x2={W - margin.right}
              y2={yScale(0.5)}
              stroke="#4a4a6a"
              strokeWidth={1.5}
              strokeDasharray="6,4"
            />
          )}

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

        {/* EV+ Info Table */}
        {evStats.evPlusCount > 0 && (
          <div className="ev-info-table">
            <h3>Statystyki EV+</h3>
            <table>
              <thead>
                <tr>
                  <th></th>
                  <th>{teamA}</th>
                  <th>{teamB}</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td className="ev-info-label">Punkty EV+</td>
                  <td className="ev-info-value ev-positive">{evStats.evPlusACount}</td>
                  <td className="ev-info-value ev-negative">{evStats.evPlusBCount}</td>
                </tr>
                {evStats.maxEvA && (
                  <tr>
                    <td className="ev-info-label">Max EV</td>
                    <td className="ev-info-value ev-positive">{((evStats.maxEvA.ev_a ?? 0) * 100).toFixed(1)}%</td>
                    <td className="ev-info-value ev-negative">{((evStats.maxEvB?.ev_b ?? 0) * 100).toFixed(1)}%</td>
                  </tr>
                )}
                {evStats.minProbA && evStats.maxProbA && (
                  <tr>
                    <td className="ev-info-label">Prawd. min</td>
                    <td className="ev-info-value">{(evStats.minProbA.value * 100).toFixed(1)}% <span className="ev-info-ts">({new Date(evStats.minProbA.ts).toLocaleString('pl-PL', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })})</span></td>
                    <td className="ev-info-value">{(evStats.minProbB!.value * 100).toFixed(1)}% <span className="ev-info-ts">({new Date(evStats.minProbB!.ts).toLocaleString('pl-PL', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })})</span></td>
                  </tr>
                )}
                {evStats.minProbA && evStats.maxProbA && (
                  <tr>
                    <td className="ev-info-label">Prawd. max</td>
                    <td className="ev-info-value">{(evStats.maxProbA.value * 100).toFixed(1)}% <span className="ev-info-ts">({new Date(evStats.maxProbA.ts).toLocaleString('pl-PL', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })})</span></td>
                    <td className="ev-info-value">{(evStats.maxProbB!.value * 100).toFixed(1)}% <span className="ev-info-ts">({new Date(evStats.maxProbB!.ts).toLocaleString('pl-PL', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })})</span></td>
                  </tr>
                )}
                {evStats.currentPoints.length > 0 && (
                  <tr>
                    <td className="ev-info-label">Aktualne prawd.</td>
                    <td className="ev-info-value">
                      {evStats.currentPoints.map((pt, i) => (
                        <span key={i}>{pt.prob_a != null ? `${(pt.prob_a * 100).toFixed(1)}%` : '—'}{i < evStats.currentPoints.length - 1 ? ' / ' : ''}</span>
                      ))}
                    </td>
                    <td className="ev-info-value">
                      {evStats.currentPoints.map((pt, i) => (
                        <span key={i}>{pt.prob_b != null ? `${(pt.prob_b * 100).toFixed(1)}%` : '—'}{i < evStats.currentPoints.length - 1 ? ' / ' : ''}</span>
                      ))}
                    </td>
                  </tr>
                )}
                {evStats.currentPoints.length > 0 && (
                  <tr>
                    <td className="ev-info-label">Aktualne EV</td>
                    <td className="ev-info-value">
                      {evStats.currentPoints.map((pt, i) => (
                        <span key={i} className={pt.ev_a != null && pt.ev_a > 0 ? 'ev-positive' : ''}>{pt.ev_a != null ? `${(pt.ev_a * 100).toFixed(1)}%` : '—'}{i < evStats.currentPoints.length - 1 ? ' / ' : ''}</span>
                      ))}
                    </td>
                    <td className="ev-info-value">
                      {evStats.currentPoints.map((pt, i) => (
                        <span key={i} className={pt.ev_b != null && pt.ev_b > 0 ? 'ev-negative' : ''}>{pt.ev_b != null ? `${(pt.ev_b * 100).toFixed(1)}%` : '—'}{i < evStats.currentPoints.length - 1 ? ' / ' : ''}</span>
                      ))}
                    </td>
                  </tr>
                )}
                {evStats.currentMarketA != null && (
                  <tr>
                    <td className="ev-info-label">Rynek (aktualne)</td>
                    <td className="ev-info-value">
                      {evStats.currentMarketA != null ? `${(evStats.currentMarketA.value * 100).toFixed(1)}%` : '—'}
                    </td>
                    <td className="ev-info-value">
                      {evStats.currentMarketB != null ? `${(evStats.currentMarketB.value * 100).toFixed(1)}%` : '—'}
                    </td>
                  </tr>
                )}
                {evStats.minMarketA && (
                  <tr>
                    <td className="ev-info-label">Rynek min</td>
                    <td className="ev-info-value">
                      {(evStats.minMarketA.value * 100).toFixed(1)}%
                      <span className="ev-info-ts"> {new Date(evStats.minMarketA.ts).toLocaleString('pl-PL', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}</span>
                    </td>
                    <td className="ev-info-value">
                      {evStats.minMarketB ? `${(evStats.minMarketB.value * 100).toFixed(1)}%` : '—'}
                      {evStats.minMarketB && <span className="ev-info-ts"> {new Date(evStats.minMarketB.ts).toLocaleString('pl-PL', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}</span>}
                    </td>
                  </tr>
                )}
                {evStats.maxMarketA && (
                  <tr>
                    <td className="ev-info-label">Rynek max</td>
                    <td className="ev-info-value">
                      {(evStats.maxMarketA.value * 100).toFixed(1)}%
                      <span className="ev-info-ts"> {new Date(evStats.maxMarketA.ts).toLocaleString('pl-PL', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}</span>
                    </td>
                    <td className="ev-info-value">
                      {evStats.maxMarketB ? `${(evStats.maxMarketB.value * 100).toFixed(1)}%` : '—'}
                      {evStats.maxMarketB && <span className="ev-info-ts"> {new Date(evStats.maxMarketB.ts).toLocaleString('pl-PL', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}</span>}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
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
  const [editingBestOf, setEditingBestOf] = useState(false);
  const [savingBestOf, setSavingBestOf] = useState(false);
  const [predicting, setPredicting] = useState(false);
  const [aliasModalSide, setAliasModalSide] = useState<'a' | 'b' | null>(null);
  const [aliasSearchQuery, setAliasSearchQuery] = useState('');
  const [aliasSearchResults, setAliasSearchResults] = useState<string[]>([]);
  const [aliasSaving, setAliasSaving] = useState(false);

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

  const fmtNum = (value: number | null | undefined, digits = 1) => (
    value == null || !Number.isFinite(value) ? '—' : value.toFixed(digits)
  );

  const fmtPct = (value: number | null | undefined, digits = 1) => (
    value == null || !Number.isFinite(value) ? '—' : `${(value * 100).toFixed(digits)}%`
  );

  const ratingProbRows = Object.entries(match.team_comparison?.rating_probabilities || {})
    .filter(([, value]) => Number.isFinite(value))
    .sort(([a], [b]) => a.localeCompare(b));

  const renderTeamSummary = (side: 'a' | 'b') => {
    const roster = side === 'a' ? match.roster_a : match.roster_b;
    const stats = side === 'a' ? match.recent_stats_a : match.recent_stats_b;
    const comparison = match.team_comparison;
    const teamName = side === 'a' ? match.team_a_name : match.team_b_name;
    const elo = side === 'a' ? comparison?.team_a_elo : comparison?.team_b_elo;
    const glicko = side === 'a' ? comparison?.team_a_glicko : comparison?.team_b_glicko;
    const rd = side === 'a' ? comparison?.team_a_glicko_rd : comparison?.team_b_glicko_rd;
    const games = side === 'a' ? comparison?.team_a_games_played : comparison?.team_b_games_played;
    return (
      <article className={`team-detail-card ${side === 'a' ? 'team-a-card' : 'team-b-card'}`}>
        <div className="team-detail-head">
          <h3>{teamName || roster?.team_name || '—'}</h3>
          <span>{roster?.team_name && roster.team_name !== teamName ? roster.team_name : 'GOL.GG / DB'}</span>
        </div>
        <div className="rating-kpis">
          <div><strong>{fmtNum(elo, 0)}</strong><span>Team Elo</span></div>
          <div><strong>{fmtNum(glicko, 0)}</strong><span>Glicko2</span></div>
          <div><strong>{fmtNum(rd, 0)}</strong><span>RD</span></div>
          <div><strong>{games ?? '—'}</strong><span>Gry ratingu</span></div>
        </div>
        {stats && (
          <div className="recent-stats-grid">
            <div><span>W20 winrate</span><strong>{fmtPct(stats.win_rate)}</strong></div>
            <div><span>Mecze / gry</span><strong>{stats.matches_count ?? '—'} / {stats.games_count ?? '—'}</strong></div>
            <div><span>K / D</span><strong>{fmtNum(stats.avg_kills)} / {fmtNum(stats.avg_deaths)}</strong></div>
            <div><span>GD@15</span><strong>{fmtNum(stats.avg_gd15, 0)}</strong></div>
            <div><span>Smoki</span><strong>{fmtNum(stats.avg_dragons)}</strong></div>
            <div><span>Nashory</span><strong>{fmtNum(stats.avg_nashors)}</strong></div>
          </div>
        )}
        {roster && (
          <div className="roster-meta">
            <span>Roster: {roster.roster_source || '—'}</span>
            <span>Źródło: {roster.source_date ? formatDateTime(roster.source_date) : '—'}</span>
            {roster.source_tournament && <span>{roster.source_tournament}</span>}
          </div>
        )}
      </article>
    );
  };

  const renderRoster = (roster: MatchDetailResponse['roster_a'], side: 'a' | 'b') => {
    const teamName = side === 'a' ? match.team_a_name : match.team_b_name;
    return (
      <article className="roster-card">
        <div className="roster-card-head">
          <h3>{teamName || roster?.team_name || '—'}</h3>
          <span>avg Elo {fmtNum(roster?.avg_elo, 0)} · avg Glicko {fmtNum(roster?.avg_glicko, 0)}</span>
        </div>
        {!roster || roster.players.length === 0 ? (
          <p className="no-data small">Brak przewidywanego rosteru w features_json.</p>
        ) : (
          <div className="players-table">
            <div className="players-header">
              <span>Rola</span><span>Zawodnik</span><span>Elo</span><span>Glicko2</span><span>RD</span><span>Gry</span>
            </div>
            {roster.players.map((player, idx) => (
              <div key={`${player.player_id || player.player_name || idx}`} className="players-row">
                <span className="role-pill">{player.role || '—'}</span>
                <span className="player-name">{player.player_name || player.player_id || '—'}</span>
                <span>{fmtNum(player.elo_rating, 0)}</span>
                <span>{fmtNum(player.glicko_rating, 0)}</span>
                <span>{fmtNum(player.glicko_rd, 0)}</span>
                <span>{player.games_played ?? '—'}</span>
              </div>
            ))}
          </div>
        )}
      </article>
    );
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
          {!editingBestOf && (
            <span
              className={`best-of-badge bo${match.best_of || 1}`}
              onClick={() => setEditingBestOf(true)}
              title="Kliknij aby zmienić"
            >
              Bo{match.best_of || 1}
            </span>
          )}
          {editingBestOf && (
            <span className="best-of-picker">
              {[1, 3, 5, 7].map(bo => (
                <button
                  key={bo}
                  className={`bo-pill ${(match.best_of || 1) === bo ? 'active' : ''} ${savingBestOf ? 'saving' : ''}`}
                  onClick={async () => {
                    if ((match.best_of || 1) === bo) {
                      setEditingBestOf(false);
                      return;
                    }
                    setSavingBestOf(true);
                    try {
                      await updateMatchBestOf(match.canonical_match_id, bo);
                      setMatch({ ...match, best_of: bo });
                    } catch {
                      // silently fail, keep old value
                    } finally {
                      setSavingBestOf(false);
                      setEditingBestOf(false);
                    }
                  }}
                  disabled={savingBestOf}
                >
                  Bo{bo}
                </button>
              ))}
            </span>
          )}
          <button
            className={`predict-btn ${predicting ? 'predicting' : ''}`}
            onClick={async () => {
              if (predicting) return;
              setPredicting(true);
              try {
                await predictMatch(match.canonical_match_id);
                // Refresh both match detail and prediction history
                const [matchData, historyData] = await Promise.all([
                  fetchMatchDetail(match.canonical_match_id),
                  fetchPredictionHistory(match.canonical_match_id),
                ]);
                setMatch(matchData);
                setPredHistory(historyData);
              } catch (err: any) {
                setError(err.message || 'Predykcja nie powiodła się');
              } finally {
                setPredicting(false);
              }
            }}
            disabled={predicting}
          >
            {predicting ? '⏳ Predykcja...' : '🔮 Predykcja'}
          </button>
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
              <span>Min kurs A</span>
              <span>Min kurs B</span>
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
                <span className="min-odds-value">
                  {pred.prob_a ? (1 / (pred.prob_a * 0.88)).toFixed(2) : '—'}
                </span>
                <span className="min-odds-value">
                  {pred.prob_b ? (1 / (pred.prob_b * 0.88)).toFixed(2) : '—'}
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

      {(match.team_comparison || match.recent_stats_a || match.recent_stats_b) && (
        <section className="match-intel-section">
          <h2>Intel przedmeczowy</h2>
          <div className="team-detail-grid">
            {renderTeamSummary('a')}
            {renderTeamSummary('b')}
          </div>
          {ratingProbRows.length > 0 && (
            <div className="rating-prob-strip">
              {ratingProbRows.map(([system, value]) => (
                <div key={system} className="rating-prob-item">
                  <span>{system.toUpperCase()}</span>
                  <strong>{fmtPct(value)}</strong>
                  <small>{match.team_a_name || 'A'}</small>
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      {(match.roster_a || match.roster_b) && (
        <section className="rosters-section">
          <h2>Przewidywane składy i ratingi zawodników</h2>
          <p className="section-hint">
            Składy pochodzą z ostatniego znanego meczu / feature cache przed spotkaniem. Ratingi są punktowe z aktualnej wersji ratingów używanej przez pipeline.
          </p>
          <div className="rosters-grid">
            {renderRoster(match.roster_a, 'a')}
            {renderRoster(match.roster_b, 'b')}
          </div>
        </section>
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
              <span className="mapping-cell">
                {match.team_comparison.team_a?.confidence
                  ? `${(match.team_comparison.team_a.confidence * 100).toFixed(0)}%`
                  : '—'}
                <button
                  className="alias-link-btn"
                  onClick={() => {
                    setAliasModalSide('a');
                    setAliasSearchQuery('');
                    setAliasSearchResults([]);
                  }}
                  title="Połącz z drużyną GolGG"
                >
                  🔗
                </button>
                {match.team_comparison.team_a?.source === 'alias' && (
                  <button
                    className="alias-delete-btn"
                    disabled={aliasSaving}
                    onClick={async () => {
                      setAliasSaving(true);
                      try {
                        await deleteTeamAlias(match.team_comparison?.team_a?.canonical_name || match.team_a_name || '');
                        const updated = await fetchMatchDetail(parseInt(id!));
                        setMatch(updated);
                      } catch (err) {
                        console.error('Failed to delete alias:', err);
                      } finally {
                        setAliasSaving(false);
                      }
                    }}
                    title="Usuń mapowanie"
                  >
                    🗑️
                  </button>
                )}
                {match.team_comparison.team_a?.source === 'blocked' && (
                  <button
                    className="alias-unblock-btn"
                    disabled={aliasSaving}
                    onClick={async () => {
                      setAliasSaving(true);
                      try {
                        await unblockTeamAlias(match.team_comparison?.team_a?.canonical_name || match.team_a_name || '');
                        const updated = await fetchMatchDetail(parseInt(id!));
                        setMatch(updated);
                      } catch (err) {
                        console.error('Failed to unblock alias:', err);
                      } finally {
                        setAliasSaving(false);
                      }
                    }}
                    title="Odblokuj mapowanie"
                  >
                    ✅
                  </button>
                )}
                {aliasModalSide === 'a' && (
                  <div className="alias-dropdown">
                    <input
                      type="text"
                      placeholder="Szukaj drużyny GolGG..."
                      value={aliasSearchQuery}
                      onChange={async (e) => {
                        setAliasSearchQuery(e.target.value);
                        if (e.target.value.length >= 2) {
                          try {
                            const res = await searchGolggTeams(e.target.value);
                            setAliasSearchResults(res.teams);
                          } catch { setAliasSearchResults([]); }
                        } else {
                          setAliasSearchResults([]);
                        }
                      }}
                      autoFocus
                    />
                    {aliasSearchResults.length > 0 && (
                      <ul className="alias-results">
                        {aliasSearchResults.slice(0, 20).map((team) => (
                          <li key={team}>
                            <button
                              disabled={aliasSaving}
                              onClick={async () => {
                                setAliasSaving(true);
                                try {
                                  await createTeamAlias({
                                    raw_name: match.team_comparison?.team_a?.canonical_name || match.team_a_name || '',
                                    golgg_team_name: team,
                                  });
                                  setAliasModalSide(null);
                                  // Refresh match detail
                                  const updated = await fetchMatchDetail(parseInt(id!));
                                  setMatch(updated);
                                } catch (err) {
                                  console.error('Failed to create alias:', err);
                                } finally {
                                  setAliasSaving(false);
                                }
                              }}
                            >
                              {team}
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                    <button className="alias-close-btn" onClick={() => setAliasModalSide(null)}>✕</button>
                  </div>
                )}
              </span>
              <span className="mapping-cell">
                {match.team_comparison.team_b?.confidence
                  ? `${(match.team_comparison.team_b.confidence * 100).toFixed(0)}%`
                  : '—'}
                <button
                  className="alias-link-btn"
                  onClick={() => {
                    setAliasModalSide('b');
                    setAliasSearchQuery('');
                    setAliasSearchResults([]);
                  }}
                  title="Połącz z drużyną GolGG"
                >
                  🔗
                </button>
                {match.team_comparison.team_b?.source === 'alias' && (
                  <button
                    className="alias-delete-btn"
                    disabled={aliasSaving}
                    onClick={async () => {
                      setAliasSaving(true);
                      try {
                        await deleteTeamAlias(match.team_comparison?.team_b?.canonical_name || match.team_b_name || '');
                        const updated = await fetchMatchDetail(parseInt(id!));
                        setMatch(updated);
                      } catch (err) {
                        console.error('Failed to delete alias:', err);
                      } finally {
                        setAliasSaving(false);
                      }
                    }}
                    title="Usuń mapowanie"
                  >
                    🗑️
                  </button>
                )}
                {match.team_comparison.team_b?.source === 'blocked' && (
                  <button
                    className="alias-unblock-btn"
                    disabled={aliasSaving}
                    onClick={async () => {
                      setAliasSaving(true);
                      try {
                        await unblockTeamAlias(match.team_comparison?.team_b?.canonical_name || match.team_b_name || '');
                        const updated = await fetchMatchDetail(parseInt(id!));
                        setMatch(updated);
                      } catch (err) {
                        console.error('Failed to unblock alias:', err);
                      } finally {
                        setAliasSaving(false);
                      }
                    }}
                    title="Odblokuj mapowanie"
                  >
                    ✅
                  </button>
                )}
                {aliasModalSide === 'b' && (
                  <div className="alias-dropdown">
                    <input
                      type="text"
                      placeholder="Szukaj drużyny GolGG..."
                      value={aliasSearchQuery}
                      onChange={async (e) => {
                        setAliasSearchQuery(e.target.value);
                        if (e.target.value.length >= 2) {
                          try {
                            const res = await searchGolggTeams(e.target.value);
                            setAliasSearchResults(res.teams);
                          } catch { setAliasSearchResults([]); }
                        } else {
                          setAliasSearchResults([]);
                        }
                      }}
                      autoFocus
                    />
                    {aliasSearchResults.length > 0 && (
                      <ul className="alias-results">
                        {aliasSearchResults.slice(0, 20).map((team) => (
                          <li key={team}>
                            <button
                              disabled={aliasSaving}
                              onClick={async () => {
                                setAliasSaving(true);
                                try {
                                  await createTeamAlias({
                                    raw_name: match.team_comparison?.team_b?.canonical_name || match.team_b_name || '',
                                    golgg_team_name: team,
                                  });
                                  setAliasModalSide(null);
                                  // Refresh match detail
                                  const updated = await fetchMatchDetail(parseInt(id!));
                                  setMatch(updated);
                                } catch (err) {
                                  console.error('Failed to create alias:', err);
                                } finally {
                                  setAliasSaving(false);
                                }
                              }}
                            >
                              {team}
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                    <button className="alias-close-btn" onClick={() => setAliasModalSide(null)}>✕</button>
                  </div>
                )}
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
            <div className="comparison-row">
              <span className="comparison-label">Team Elo</span>
              <span>{fmtNum(match.team_comparison.team_a_elo, 0)}</span>
              <span>{fmtNum(match.team_comparison.team_b_elo, 0)}</span>
            </div>
            <div className="comparison-row">
              <span className="comparison-label">Team Glicko2 / RD</span>
              <span>{fmtNum(match.team_comparison.team_a_glicko, 0)} / {fmtNum(match.team_comparison.team_a_glicko_rd, 0)}</span>
              <span>{fmtNum(match.team_comparison.team_b_glicko, 0)} / {fmtNum(match.team_comparison.team_b_glicko_rd, 0)}</span>
            </div>
            {match.team_comparison.team_a_rating && match.team_comparison.team_b_rating && (
              <div className="comparison-row">
                <span className="comparison-label">Różnica ratingów</span>
                <span className="rating-diff">
                  {(match.team_comparison.team_a_rating - match.team_comparison.team_b_rating) > 0 ? '+' : ''}
                  {(match.team_comparison.team_a_rating - match.team_comparison.team_b_rating).toFixed(1)}
                </span>
                <span className="rating-diff-muted">
                  {match.team_comparison.rating_system || 'rating'}
                </span>
              </div>
            )}
          </div>
        </section>
      )}
    </div>
  );
}
