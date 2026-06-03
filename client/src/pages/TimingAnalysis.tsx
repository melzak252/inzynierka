import { useState, useEffect } from 'react';
import { fetchTimingAnalysis } from '../api/client';
import type { TimingAnalysisResponse, TimingBucket } from '../types';
import './TimingAnalysis.css';

export default function TimingAnalysis() {
  const [data, setData] = useState<TimingAnalysisResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [daysBack, setDaysBack] = useState(60);

  useEffect(() => {
    loadData();
  }, [daysBack]);

  async function loadData() {
    setLoading(true);
    setError(null);
    try {
      const result = await fetchTimingAnalysis(daysBack);
      setData(result);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load timing analysis');
    } finally {
      setLoading(false);
    }
  }

  if (loading) {
    return (
      <div className="timing-page">
        <h1>⏱ Timing Analysis</h1>
        <p className="loading-text">Loading odds movement data...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="timing-page">
        <h1>⏱ Timing Analysis</h1>
        <p className="error-text">Error: {error}</p>
      </div>
    );
  }

  if (!data || data.total_matches === 0) {
    return (
      <div className="timing-page">
        <h1>⏱ Timing Analysis</h1>
        <div className="timing-controls">
          <label>
            Days back:
            <select value={daysBack} onChange={e => setDaysBack(Number(e.target.value))}>
              <option value={30}>30 days</option>
              <option value={60}>60 days</option>
              <option value={90}>90 days</option>
              <option value={180}>180 days</option>
            </select>
          </label>
        </div>
        <div className="empty-state">
          <p>No finished matches with odds history found for the selected period.</p>
          <p className="hint">Try selecting a longer period or check if scrapers have collected enough data.</p>
        </div>
      </div>
    );
  }

  const { time_buckets, drift_summary, best_betting_window } = data;

  // Compute combined market deviation per bucket (avg of A and B)
  const bucketsWithMarket = time_buckets.map(b => ({
    ...b,
    avg_market_deviation_pct: (b.avg_deviation_a_pct + b.avg_deviation_b_pct) / 2,
  }));

  // Sort by market deviation descending (best = most positive first)
  const sortedByMarket = [...bucketsWithMarket].sort(
    (a, z) => z.avg_market_deviation_pct - a.avg_market_deviation_pct
  );

  return (
    <div className="timing-page">
      <h1>⏱ Timing Analysis</h1>

      <div className="timing-controls">
        <label>
          Period:
          <select value={daysBack} onChange={e => setDaysBack(Number(e.target.value))}>
            <option value={30}>30 days</option>
            <option value={60}>60 days</option>
            <option value={90}>90 days</option>
            <option value={180}>180 days</option>
          </select>
        </label>
        <span className="stats-badge">
          {data.total_matches} matches · {data.total_snapshots} snapshots
        </span>
      </div>

      {best_betting_window && (
        <div className="spotlight-card">
          <h2>⭐ Best Betting Window</h2>
          <div className="spotlight-content">
            <div className="spotlight-main">
              <span className="spotlight-bucket">{best_betting_window.bucket}</span>
              <span className="spotlight-label">before match start</span>
            </div>
            <div className="spotlight-metrics">
              <div className="spotlight-metric">
                <span className="metric-value positive">
                  {best_betting_window.avg_favorable_deviation_pct > 0 ? '+' : ''}
                  {best_betting_window.avg_favorable_deviation_pct.toFixed(1)}%
                </span>
                <span className="metric-label">best avg deviation from closing</span>
              </div>
              <div className="spotlight-metric">
                <span className="metric-value">{best_betting_window.match_count}</span>
                <span className="metric-label">matches in sample</span>
              </div>
              <div className="spotlight-metric">
                <span className="metric-value">{best_betting_window.snapshot_count}</span>
                <span className="metric-label">total snapshots</span>
              </div>
            </div>
          </div>
          <p className="spotlight-recommendation">{best_betting_window.recommendation}</p>
        </div>
      )}

      {/* SVG Deviation Chart */}
      <div className="chart-section">
        <h2>Odds Deviation from Closing</h2>
        <p className="chart-subtitle">
          Positive % = odds better than closing · Negative % = odds worse than closing
          · Dashed line = market average (Team A + Team B) / 2
        </p>
        <div className="chart-container">
          <OddsDeviationChart buckets={bucketsWithMarket} />
        </div>
      </div>

      {/* Overall Market Ranking */}
      {sortedByMarket.length >= 2 && (
        <div className="ranking-section">
          <h2>📊 Market Overview — When to Bet</h2>
          <div className="ranking-grid">
            {sortedByMarket.map((b, i) => {
              const isBest = i === 0;
              const isWorst = i === sortedByMarket.length - 1;
              return (
                <div
                  key={b.bucket}
                  className={`ranking-card ${isBest ? 'best' : ''} ${isWorst ? 'worst' : ''}`}
                >
                  <span className="ranking-pos">#{i + 1}</span>
                  <span className="ranking-bucket">{b.bucket}</span>
                  <span className={`ranking-value ${b.avg_market_deviation_pct >= 0 ? 'positive' : 'negative'}`}>
                    {b.avg_market_deviation_pct > 0 ? '+' : ''}
                    {b.avg_market_deviation_pct.toFixed(2)}%
                  </span>
                  <div className="ranking-bar-wrapper">
                    <div
                      className="ranking-bar"
                      style={{
                        width: `${Math.abs(b.avg_market_deviation_pct) / Math.max(...sortedByMarket.map(x => Math.abs(x.avg_market_deviation_pct))) * 100}%`,
                        background: b.avg_market_deviation_pct >= 0
                          ? 'linear-gradient(90deg, #2ecc71, #4caf50)'
                          : 'linear-gradient(90deg, #ef5350, #e53935)',
                      }}
                    />
                  </div>
                  <div className="ranking-detail">
                    A {b.avg_deviation_a_pct > 0 ? '+' : ''}{b.avg_deviation_a_pct.toFixed(1)}%
                    · B {b.avg_deviation_b_pct > 0 ? '+' : ''}{b.avg_deviation_b_pct.toFixed(1)}%
                  </div>
                  <div className="ranking-meta">
                    {b.match_count} meczów · {b.snapshot_count} snap
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Trend Cards */}
      {time_buckets.length >= 2 && (
        <div className="trend-section">
          <h2>Trend by Time Bucket</h2>
          <div className="trend-grid">
            {time_buckets.map((b, i) => {
              const prev = i > 0 ? time_buckets[i - 1] : null;
              return (
                <TrendCard key={b.bucket} bucket={b} prev={prev} />
              );
            })}
          </div>
        </div>
      )}

      {/* Drift Summary */}
      {drift_summary && (
        <div className="drift-section">
          <h2>Convergence Analysis</h2>
          <div className="drift-grid">
            <div className={`drift-card ${drift_summary.convergence_a_pct > 0 ? 'positive' : 'negative'}`}>
              <h3>Team A</h3>
              <p className="drift-numbers">
                {drift_summary.open_deviation_a_pct > 0 ? '+' : ''}
                {drift_summary.open_deviation_a_pct.toFixed(1)}% → {' '}
                {drift_summary.close_deviation_a_pct > 0 ? '+' : ''}
                {drift_summary.close_deviation_a_pct.toFixed(1)}%
              </p>
              <p className="drift-desc">
                {drift_summary.convergence_a_pct > 0
                  ? `Converging toward closing (${drift_summary.convergence_a_pct.toFixed(1)}% closer)`
                  : `Diverging from closing (${Math.abs(drift_summary.convergence_a_pct).toFixed(1)}% further)`}
              </p>
            </div>
            <div className={`drift-card ${drift_summary.convergence_b_pct > 0 ? 'positive' : 'negative'}`}>
              <h3>Team B</h3>
              <p className="drift-numbers">
                {drift_summary.open_deviation_b_pct > 0 ? '+' : ''}
                {drift_summary.open_deviation_b_pct.toFixed(1)}% → {' '}
                {drift_summary.close_deviation_b_pct > 0 ? '+' : ''}
                {drift_summary.close_deviation_b_pct.toFixed(1)}%
              </p>
              <p className="drift-desc">
                {drift_summary.convergence_b_pct > 0
                  ? `Converging toward closing (${drift_summary.convergence_b_pct.toFixed(1)}% closer)`
                  : `Diverging from closing (${Math.abs(drift_summary.convergence_b_pct).toFixed(1)}% further)`}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Raw Data Table */}
      <details className="raw-data">
        <summary>📊 Show raw data</summary>
        <table>
          <thead>
            <tr>
              <th>Bucket</th>
              <th>Snapshots</th>
              <th>Matches</th>
              <th>Dev A %</th>
              <th>Dev B %</th>
              <th>Avg Odds A</th>
              <th>Avg Odds B</th>
              <th>Closing A</th>
              <th>Closing B</th>
            </tr>
          </thead>
          <tbody>
            {time_buckets.map(b => (
              <tr key={b.bucket}>
                <td>{b.bucket}</td>
                <td>{b.snapshot_count}</td>
                <td>{b.match_count}</td>
                <td className={b.avg_deviation_a_pct > 0 ? 'positive' : 'negative'}>
                  {b.avg_deviation_a_pct > 0 ? '+' : ''}{b.avg_deviation_a_pct.toFixed(2)}%
                </td>
                <td className={b.avg_deviation_b_pct > 0 ? 'positive' : 'negative'}>
                  {b.avg_deviation_b_pct > 0 ? '+' : ''}{b.avg_deviation_b_pct.toFixed(2)}%
                </td>
                <td>{b.avg_odds_a.toFixed(3)}</td>
                <td>{b.avg_odds_b.toFixed(3)}</td>
                <td>{b.avg_closing_odds_a.toFixed(3)}</td>
                <td>{b.avg_closing_odds_b.toFixed(3)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  );
}

/* ─── SVG Deviation Chart ──────────────────────────────── */

function OddsDeviationChart({ buckets }: { buckets: (TimingBucket & { avg_market_deviation_pct?: number })[] }) {
  const chartW = 700;
  const chartH = 320;
  const pad = { top: 30, right: 30, bottom: 50, left: 60 };
  const plotW = chartW - pad.left - pad.right;
  const plotH = chartH - pad.top - pad.bottom;

  if (buckets.length < 2) {
    return <p className="chart-empty">Not enough data points for a chart.</p>;
  }

  // Find max absolute deviation for Y scale
  const allDevs = buckets.flatMap(b => [
    b.avg_deviation_a_pct,
    b.avg_deviation_b_pct,
    b.avg_market_deviation_pct ?? 0,
  ]);
  const maxAbsDev = Math.max(Math.abs(Math.min(...allDevs)), Math.abs(Math.max(...allDevs)), 0.5);
  const yMax = Math.ceil(maxAbsDev * 1.15); // +15% headroom
  const yMin = -yMax;

  // X values: hours_start
  const xMin = buckets[0].hours_start;
  const xMax = buckets[buckets.length - 1].hours_end;

  function xPos(hours: number): number {
    return pad.left + ((hours - xMin) / (xMax - xMin)) * plotW;
  }

  function yPos(pct: number): number {
    return pad.top + plotH - ((pct - yMin) / (yMax - yMin)) * plotH;
  }

  // Helper to build path
  const buildPath = (getVal: (b: typeof buckets[number]) => number) =>
    buckets.map((b, i) => {
      const x = xPos(b.hours_start + (b.hours_end - b.hours_start) / 2);
      const y = yPos(getVal(b));
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(' ');

  const pathA = buildPath(b => b.avg_deviation_a_pct);
  const pathB = buildPath(b => b.avg_deviation_b_pct);
  const pathM = buildPath(b => b.avg_market_deviation_pct ?? 0);

  // Y-axis ticks
  const yTicks = [];
  const yStep = Math.max(1, Math.ceil(yMax / 4));
  for (let v = -yMax; v <= yMax; v += yStep) {
    yTicks.push(v);
  }

  // X-axis labels — show every other bucket to avoid crowding
  const xLabels = buckets.filter((_, i) => i % 2 === 0 || i === buckets.length - 1);

  // Zero line
  const zeroY = yPos(0);

  return (
    <svg viewBox={`0 0 ${chartW} ${chartH}`} className="deviation-chart">
      {/* Grid lines */}
      {yTicks.map(v => (
        <g key={v}>
          <line
            x1={pad.left} y1={yPos(v)}
            x2={chartW - pad.right} y2={yPos(v)}
            stroke="#2a2a4a" strokeWidth={1}
          />
          <text x={pad.left - 8} y={yPos(v) + 4} textAnchor="end" fill="#888" fontSize={11}>
            {v > 0 ? '+' : ''}{v}%
          </text>
        </g>
      ))}

      {/* Zero line */}
      <line
        x1={pad.left} y1={zeroY}
        x2={chartW - pad.right} y2={zeroY}
        stroke="#4a4a6a" strokeWidth={1.5} strokeDasharray="4 3"
      />
      <text x={pad.left - 8} y={zeroY - 4} textAnchor="end" fill="#888" fontSize={10}>
        0% (closing)
      </text>

      {/* X-axis labels */}
      {xLabels.map(b => {
        const cx = xPos(b.hours_start + (b.hours_end - b.hours_start) / 2);
        return (
          <text key={b.bucket} x={cx} y={chartH - 10} textAnchor="end" fill="#888" fontSize={10} transform={`rotate(-35, ${cx}, ${chartH - 10})`}>
            {b.bucket}
          </text>
        );
      })}

      {/* X-axis title */}
      <text x={chartW / 2} y={chartH - 4} textAnchor="middle" fill="#aaa" fontSize={11}>
        Hours before match →
      </text>

      {/* Y-axis title */}
      <text x={12} y={chartH / 2} textAnchor="middle" fill="#aaa" fontSize={11} transform={`rotate(-90, 12, ${chartH / 2})`}>
        % Deviation from closing
      </text>

      {/* Data line — Market average (dashed, behind others) */}
      <path d={pathM} fill="none" stroke="#e040fb" strokeWidth={2} strokeDasharray="6 4" opacity={0.8} />

      {/* Data line — Team A */}
      <path d={pathA} fill="none" stroke="#4fc3f7" strokeWidth={2.5} />

      {/* Data line — Team B */}
      <path d={pathB} fill="none" stroke="#ff9800" strokeWidth={2.5} />

      {/* Data points — Market */}
      {buckets.map((b) => {
        const cx = xPos(b.hours_start + (b.hours_end - b.hours_start) / 2);
        const cy = yPos(b.avg_market_deviation_pct ?? 0);
        return (
          <circle key={`m-${b.bucket}`} cx={cx} cy={cy} r={3} fill="#e040fb" stroke="#1a1a2e" strokeWidth={1.5}>
            <title>Market avg: {b.avg_market_deviation_pct !== undefined ? `${b.avg_market_deviation_pct > 0 ? '+' : ''}${b.avg_market_deviation_pct.toFixed(2)}%` : 'N/A'}</title>
          </circle>
        );
      })}

      {/* Data points — Team A */}
      {buckets.map((b) => {
        const cx = xPos(b.hours_start + (b.hours_end - b.hours_start) / 2);
        const cy = yPos(b.avg_deviation_a_pct);
        return (
          <circle key={`a-${b.bucket}`} cx={cx} cy={cy} r={3.5} fill="#4fc3f7" stroke="#1a1a2e" strokeWidth={1.5}>
            <title>Team A: {b.avg_deviation_a_pct > 0 ? '+' : ''}{b.avg_deviation_a_pct.toFixed(2)}%</title>
          </circle>
        );
      })}

      {/* Data points — Team B */}
      {buckets.map((b) => {
        const cx = xPos(b.hours_start + (b.hours_end - b.hours_start) / 2);
        const cy = yPos(b.avg_deviation_b_pct);
        return (
          <circle key={`b-${b.bucket}`} cx={cx} cy={cy} r={3.5} fill="#ff9800" stroke="#1a1a2e" strokeWidth={1.5}>
            <title>Team B: {b.avg_deviation_b_pct > 0 ? '+' : ''}{b.avg_deviation_b_pct.toFixed(2)}%</title>
          </circle>
        );
      })}

      {/* Data labels — every other point to avoid clutter */}
      {buckets.map((b, i) => {
        if (i % 2 !== 0 && i !== buckets.length - 1) return null;
        const cx = xPos(b.hours_start + (b.hours_end - b.hours_start) / 2);
        const ay = yPos(b.avg_deviation_a_pct);
        const by = yPos(b.avg_deviation_b_pct);
        return (
          <g key={`label-${b.bucket}`}>
            <text x={cx + 8} y={ay - 6} fill="#4fc3f7" fontSize={10}>
              {b.avg_deviation_a_pct > 0 ? '+' : ''}{b.avg_deviation_a_pct.toFixed(1)}%
            </text>
            <text x={cx + 8} y={by + 14} fill="#ff9800" fontSize={10}>
              {b.avg_deviation_b_pct > 0 ? '+' : ''}{b.avg_deviation_b_pct.toFixed(1)}%
            </text>
          </g>
        );
      })}

      {/* Legend */}
      <g transform={`translate(${chartW - pad.right - 180}, 8)`}>
        <rect x={0} y={0} width={180} height={60} rx={6} fill="#1a1a2e" stroke="#2a2a4a" />
        <circle cx={16} cy={16} r={5} fill="#4fc3f7" />
        <text x={28} y={20} fill="#ccc" fontSize={12}>Team A deviation</text>
        <circle cx={16} cy={36} r={5} fill="#ff9800" />
        <text x={28} y={40} fill="#ccc" fontSize={12}>Team B deviation</text>
        <line x1={11} y1={52} x2={21} y2={52} stroke="#e040fb" strokeWidth={2} strokeDasharray="4 3" />
        <text x={28} y={56} fill="#ccc" fontSize={12}>Market avg</text>
      </g>
    </svg>
  );
}

/* ─── Trend Card ───────────────────────────────────────── */

function TrendCard({ bucket, prev }: { bucket: TimingBucket; prev: TimingBucket | null }) {
  const dir = (current: number, previous: number | null): 'up' | 'down' | 'flat' => {
    if (previous === null) return 'flat';
    const diff = current - previous;
    if (diff > 0.5) return 'up';
    if (diff < -0.5) return 'down';
    return 'flat';
  };

  const dirA = dir(bucket.avg_deviation_a_pct, prev?.avg_deviation_a_pct ?? null);
  const dirB = dir(bucket.avg_deviation_b_pct, prev?.avg_deviation_b_pct ?? null);

  const arrow = (d: 'up' | 'down' | 'flat') => {
    switch (d) {
      case 'up': return '↑';
      case 'down': return '↓';
      case 'flat': return '→';
    }
  };

  return (
    <div className="trend-card">
      <h3>{bucket.bucket}</h3>
      <div className="trend-row">
        <span className="trend-label">Team A</span>
        <span className={`trend-value ${bucket.avg_deviation_a_pct > 0 ? 'positive' : 'negative'}`}>
          {bucket.avg_deviation_a_pct > 0 ? '+' : ''}{bucket.avg_deviation_a_pct.toFixed(1)}%
        </span>
        <span className={`trend-arrow ${dirA}`}>{arrow(dirA)}</span>
      </div>
      <div className="trend-row">
        <span className="trend-label">Team B</span>
        <span className={`trend-value ${bucket.avg_deviation_b_pct > 0 ? 'positive' : 'negative'}`}>
          {bucket.avg_deviation_b_pct > 0 ? '+' : ''}{bucket.avg_deviation_b_pct.toFixed(1)}%
        </span>
        <span className={`trend-arrow ${dirB}`}>{arrow(dirB)}</span>
      </div>
      <div className="trend-meta">
        {bucket.snapshot_count} snapshots · {bucket.match_count} matches
      </div>
    </div>
  );
}
