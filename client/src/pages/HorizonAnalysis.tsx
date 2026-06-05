import { useState, useEffect, useCallback } from 'react';
import { HorizonAccuracyResponse } from '../types';
import { fetchHorizonAccuracy } from '../api/client';
import './HorizonAnalysis.css';

/* ─── Color palette ─────────────────────────────────────── */
const COLORS = {
  bar:    '#4fc3f7',
  logloss:'#e040fb',
  auc:    '#ff9800',
  grid:   '#2a2a4a',
  axis:   '#888',
  label:  '#aaa',
  title:  '#fff',
  modelHybrid:  '#00e676',
  modelBase:    '#fdd835',
  modelThesis:  '#ff6b9d',
  modelThesisHybrid: '#00d4ff',
};

/* ─── Chart dimensions ──────────────────────────────────── */
const CHART_W = 800;
const CHART_H = 340;
const PAD = { top: 30, right: 120, bottom: 70, left: 60 };

/* ─── Helpers ───────────────────────────────────────────── */
function fmt(v: number, d = 3): string {
  return v.toFixed(d);
}

function yScale(domain: [number, number]): (v: number) => number {
  const [ymin, ymax] = domain;
  const rangeH = CHART_H - PAD.top - PAD.bottom;
  return (v: number) => PAD.top + rangeH - ((v - ymin) / (ymax - ymin)) * rangeH;
}

function xPos(i: number, total: number): number {
  const rangeW = CHART_W - PAD.left - PAD.right;
  return PAD.left + (i + 0.5) * (rangeW / total);
}

/* ─── Stat card ─────────────────────────────────────────── */
function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="stat-card">
      <span className="stat-label">{label}</span>
      <span className="stat-value">{value}</span>
    </div>
  );
}

/* ─── Horizon bin y-ticks ───────────────────────────────── */
function yAxisTicks(domain: [number, number]): number[] {
  const [lo, hi] = domain;
  const raw = Math.abs(hi - lo);
  const rough = raw / 5;
  const mag = Math.pow(10, Math.floor(Math.log10(rough)));
  const nice = [1, 2, 2.5, 5, 10].find(v => v * mag >= rough)! * mag;
  const start = Math.floor(lo / nice) * nice;
  const ticks: number[] = [];
  for (let v = start; v <= hi + nice * 0.5; v = +(v + nice).toFixed(6)) {
    ticks.push(v);
  }
  return ticks;
}

/* ════════════════════════════════════════════════════════════
   Component
   ════════════════════════════════════════════════════════════ */
export default function HorizonAnalysis() {
  const [data, setData] = useState<HorizonAccuracyResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [daysBack, setDaysBack] = useState(90);
  const [minMatches, setMinMatches] = useState(10);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchHorizonAccuracy(daysBack, minMatches);
      setData(res);
    } catch (e: any) {
      setError(e.message ?? 'Failed to load');
    } finally {
      setLoading(false);
    }
  }, [daysBack, minMatches]);

  useEffect(() => { load(); }, [load]);

  /* ─── Bin availability info ──────────────────────────── */
  const allBins = data?.bins ?? [];
  const shownBins = allBins.filter(b => b.match_count >= minMatches);
  const shownCount = shownBins.length;
  const skippedCount = allBins.length - shownCount;

  /* ─── Loading / Error ────────────────────────────────── */
  if (loading) {
    return (
      <div className="horizon-page">
        <h1>Odds Horizon Accuracy</h1>
        <p className="loading-text">Loading…</p>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="horizon-page">
        <h1>Odds Horizon Accuracy</h1>
        <p className="error-text">{error ?? 'No data'}</p>
      </div>
    );
  }

  /* ─── Histogram chart (match count per bin) ────────── */
  function HistogramChart() {
    const bins = allBins;
    const n = bins.length;
    if (n === 0) return <p className="no-data">No bins returned.</p>;
    const maxCount = Math.max(...bins.map(b => b.match_count));
    const domain: [number, number] = [0, maxCount * 1.15 || 1];
    const y = yScale(domain);
    const ticks = yAxisTicks(domain);
    const barW = Math.min(50, (CHART_W - PAD.left - PAD.right) / n * 0.7);

    return (
      <div className="chart-section">
        <h3>Histogram — Match count per horizon bin</h3>
        <svg viewBox={`0 0 ${CHART_W} ${CHART_H}`} className="horizon-chart">
          {/* Y grid */}
          {ticks.map(v => (
            <g key={v}>
              <line x1={PAD.left} y1={y(v)} x2={CHART_W - PAD.right} y2={y(v)} stroke={COLORS.grid} strokeWidth={1} />
              <text x={PAD.left - 6} y={y(v) + 4} textAnchor="end" fill={COLORS.axis} fontSize={11}>{Math.round(v)}</text>
            </g>
          ))}
          {/* Bars */}
          {bins.map((b, i) => {
            const cx = xPos(i, n);
            const barH = CHART_H - PAD.top - PAD.bottom - (y(b.match_count) - PAD.top);
            const barY = y(b.match_count);
            const isSkipped = b.match_count < minMatches;
            return (
              <g key={b.label}>
                <rect x={cx - barW / 2} y={barY} width={barW} height={barH}
                  fill={isSkipped ? '#555' : COLORS.bar} opacity={isSkipped ? 0.5 : 0.85} rx={2}>
                  <title>
                    {b.label}: {b.match_count} matches, {b.snapshot_count} snapshots
                    {isSkipped ? ' (SKIPPED — <10 matches)' : ''}
                  </title>
                </rect>
                <text x={cx} y={barY - 6} textAnchor="middle" fill={COLORS.label} fontSize={10}>
                  {b.match_count}
                </text>
                <text x={cx} y={CHART_H - 10} textAnchor="end" fill={COLORS.axis} fontSize={9}
                  transform={`rotate(-30, ${cx}, ${CHART_H - 10})`}>
                  {b.label}
                </text>
              </g>
            );
          })}
          {/* Y-axis title */}
          <text x={14} y={CHART_H / 2} textAnchor="middle" fill={COLORS.label} fontSize={11}
            transform={`rotate(-90, 14, ${CHART_H / 2})`}>Matches</text>
        </svg>
      </div>
    );
  }

  /* ─── Model reference lines (pure models only) ───────── */
  function ModelRefLines({ metricKey, domain }: {
    metricKey: 'avg_logloss' | 'avg_auc';
    domain: [number, number];
  }) {
    const refs = data?.model_references ?? [];
    if (refs.length === 0) return null;
    const y = yScale(domain);

    return (
      <>
        {refs.map(r => {
          const val = r[metricKey];
          if (val === null || val === undefined) return null;
          const cy = y(val);
          const nameLower = r.model_name.toLowerCase();
          // Skip hybrid models — they're drawn as dynamic lines
          if (nameLower.includes('hybrid')) return null;
          
          let color: string;
          let label: string;
          if (nameLower.includes('thesis') || nameLower.includes('sym-cal')) {
            color = COLORS.modelThesis;
            label = 'Thesis';
          } else {
            color = COLORS.modelBase;
            label = 'Base model';
          }
          return (
            <g key={r.model_name}>
              {/* Dashed reference line */}
              <line x1={PAD.left} y1={cy} x2={CHART_W - PAD.right + 80} y2={cy}
                stroke={color} strokeWidth={1.5} strokeDasharray="6,4" opacity={0.8} />
              {/* Label + value */}
              <text x={CHART_W - PAD.right + 4} y={cy - 4} fill={color} fontSize={10}>
                {label}
              </text>
              <text x={CHART_W - PAD.right + 4} y={cy + 8} fill={color} fontSize={9}
                opacity={0.8}>
                {fmt(val)} ({r.n_matches} matches)
              </text>
            </g>
          );
        })}
      </>
    );
  }

  /* ─── Dynamic hybrid lines (per-bin metrics) ─────────── */
  function HybridDynamicLines({ metricKey, domain }: {
    metricKey: 'avg_logloss' | 'avg_auc';
    domain: [number, number];
  }) {
    const hybridBins = data?.hybrid_model_bins ?? [];
    if (hybridBins.length === 0) return null;
    const y = yScale(domain);
    const shownBins = data?.bins ?? [];
    const n = shownBins.length;
    if (n === 0) return null;

    return (
      <>
        {hybridBins.map(hb => {
          const nameLower = hb.model_name.toLowerCase();
          const color = nameLower.includes('thesis') ? COLORS.modelThesisHybrid : COLORS.modelHybrid;
          const label = nameLower.includes('thesis') ? 'Thesis Hybrid' : 'Hybrid';
          
          // Build path from bins
          const points: { x: number; y: number; bin: any }[] = [];
          hb.bins.forEach((bin, i) => {
            const val = bin[metricKey];
            if (val !== null && val !== undefined && bin.match_count >= minMatches) {
              const cx = xPos(i, n);
              const cy = y(val);
              points.push({ x: cx, y: cy, bin });
            }
          });
          
          if (points.length === 0) return null;
          
          const pathD = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x},${p.y}`).join(' ');
          
          return (
            <g key={hb.model_name}>
              {/* Dashed line connecting bins */}
              <path d={pathD} fill="none" stroke={color} strokeWidth={1.5} 
                strokeDasharray="6,4" opacity={0.8} />
              {/* Points at each bin */}
              {points.map((p, i) => (
                <circle key={i} cx={p.x} cy={p.y} r={3} fill={color} stroke="#1a1a2e" strokeWidth={1}>
                  <title>{p.bin.label}: {metricKey}={fmt(p.bin[metricKey] ?? 0)} ({p.bin.match_count} matches, {p.bin.snapshot_count} snapshots)</title>
                </circle>
              ))}
              {/* Label at last point */}
              {points.length > 0 && (
                <text x={points[points.length - 1].x + 8} y={points[points.length - 1].y - 6} 
                  fill={color} fontSize={9} opacity={0.9}>
                  {label}
                </text>
              )}
            </g>
          );
        })}
      </>
    );
  }

  /* ─── Per-bookmaker lines (subtle) ───────────────────── */
  function BookmakerLines({ metricKey, domain }: {
    metricKey: 'avg_logloss' | 'avg_auc';
    domain: [number, number];
  }) {
    const bkBins = data?.bookmaker_bins ?? [];
    if (bkBins.length === 0) return null;
    const y = yScale(domain);
    const shownBins = data?.bins ?? [];
    const n = shownBins.length;
    if (n === 0) return null;

    // Subtle color palette for bookmakers
    const bkColors = [
      '#8e99a4', '#a3b1bf', '#7c8c9a', '#9ea8b3', '#6b7b8a',
      '#b0bec5', '#90a4ae', '#78909c', '#607d8b', '#546e7a',
    ];

    return (
      <>
        {bkBins.map((bk, bkIdx) => {
          const color = bkColors[bkIdx % bkColors.length];

          // Build path from bins — match by label to the shown bins x-positions
          const points: { x: number; y: number; bin: any }[] = [];
          bk.bins.forEach((bin) => {
            const val = bin[metricKey];
            if (val !== null && val !== undefined && bin.match_count >= minMatches) {
              // Find the x-position by matching the bin label to the shown bins
              const binIdx = shownBins.findIndex(sb => sb.label === bin.label);
              if (binIdx < 0) return;
              const cx = xPos(binIdx, n);
              const cy = y(val);
              points.push({ x: cx, y: cy, bin });
            }
          });

          if (points.length === 0) return null;

          const pathD = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x},${p.y}`).join(' ');

          return (
            <g key={`bk-${bk.bookmaker_id}`}>
              <path d={pathD} fill="none" stroke={color} strokeWidth={1}
                strokeDasharray="3,3" opacity={0.45} />
              {points.map((p, i) => (
                <circle key={i} cx={p.x} cy={p.y} r={2} fill={color} opacity={0.4}>
                  <title>{bk.bookmaker_name} {p.bin.label}: {metricKey}={fmt(p.bin[metricKey] ?? 0)} ({p.bin.match_count} matches)</title>
                </circle>
              ))}
            </g>
          );
        })}
      </>
    );
  }

  /* ─── Shared line chart ───────────────────────────────── */
  function MetricLineChart({
    title,
    metricKey,
    color,
    yLabel,
    domain,
  }: {
    title: string;
    metricKey: 'avg_logloss' | 'avg_auc';
    color: string;
    yLabel: string;
    domain: [number, number];
  }) {
    const bins = shownBins;
    const n = bins.length;
    if (n === 0) return <p className="no-data">No bins with ≥{minMatches} matches.</p>;
    const y = yScale(domain);
    const ticks = yAxisTicks(domain);

    const pathD = bins.map((b, i) => {
      const cx = xPos(i, n);
      const val = b[metricKey];
      if (val === null || val === undefined) return '';
      const cy = y(val);
      return `${i === 0 ? 'M' : 'L'}${cx},${cy}`;
    }).filter(d => d !== '').join(' ');

    return (
      <div className="chart-section">
        <h3>{title}</h3>
        <svg viewBox={`0 0 ${CHART_W} ${CHART_H}`} className="horizon-chart">
          {/* Y grid */}
          {ticks.map(v => (
            <g key={v}>
              <line x1={PAD.left} y1={y(v)} x2={CHART_W - PAD.right} y2={y(v)} stroke={COLORS.grid} strokeWidth={1} />
              <text x={PAD.left - 6} y={y(v) + 4} textAnchor="end" fill={COLORS.axis} fontSize={11}>{fmt(v)}</text>
            </g>
          ))}
          {/* Model reference lines (pure models) */}
          <ModelRefLines metricKey={metricKey} domain={domain} />
          {/* Dynamic hybrid lines (per-bin) */}
          <HybridDynamicLines metricKey={metricKey} domain={domain} />
          {/* Per-bookmaker lines (subtle, behind main line) */}
          <BookmakerLines metricKey={metricKey} domain={domain} />
          {/* Line */}
          <path d={pathD} fill="none" stroke={color} strokeWidth={2.5} />
          {/* Points + labels */}
          {bins.map((b, i) => {
            const cx = xPos(i, n);
            const val = b[metricKey];
            if (val === null || val === undefined) return null;
            const cy = y(val);
            return (
              <g key={b.label}>
                <circle cx={cx} cy={cy} r={4} fill={color} stroke="#1a1a2e" strokeWidth={1.5}>
                  <title>{b.label}: {metricKey}={fmt(val)} ({b.match_count} matches)</title>
                </circle>
                <text x={cx + 8} y={cy - 6} fill={color} fontSize={10}>
                  {fmt(val)}
                </text>
                <text x={cx} y={CHART_H - 10} textAnchor="end" fill={COLORS.axis} fontSize={9}
                  transform={`rotate(-30, ${cx}, ${CHART_H - 10})`}>
                  {b.label}
                </text>
              </g>
            );
          })}
          {/* Y-axis title */}
          <text x={14} y={CHART_H / 2} textAnchor="middle" fill={COLORS.label} fontSize={11}
            transform={`rotate(-90, 14, ${CHART_H / 2})`}>{yLabel}</text>
        </svg>
      </div>
    );
  }

  /* ══════════════ RENDER ════════════════════════════════ */
  return (
    <div className="horizon-page">
      <h1>Odds Horizon Accuracy</h1>
      <p className="subtitle">
        How implied probabilities from pre-match odds predict match outcomes,
        grouped by hours before match start.
      </p>

      {/* Controls */}
      <div className="horizon-controls">
        <label>
          Days back:
          <select value={daysBack} onChange={e => setDaysBack(+e.target.value)}>
            {[30, 60, 90, 180, 365].map(d => <option key={d} value={d}>{d}</option>)}
          </select>
        </label>
        <label>
          Min matches per bin:
          <input type="number" min={1} max={100} value={minMatches}
            onChange={e => setMinMatches(Math.max(1, +e.target.value))} />
        </label>
        <button onClick={load} disabled={loading}>
          {loading ? 'Loading…' : 'Refresh'}
        </button>
      </div>

      {/* Stats row */}
      <div className="stats-row">
        <StatCard label="Finished matches" value={data.total_finished_matches} />
        <StatCard label="With odds" value={data.total_matches_with_odds} />
        <StatCard label="Odds snapshots" value={data.total_odds_processed} />
        <StatCard label="Bins shown" value={`${shownCount}/${allBins.length}`} />
        {skippedCount > 0 && <StatCard label="Bins skipped (<10 matches)" value={skippedCount} />}
      </div>

      {/* ─── Chart 1: Histogram ──────────────────────────── */}
      <HistogramChart />

      {/* ─── Chart 2: LogLoss ────────────────────────────── */}
      <MetricLineChart
        title="LogLoss by hours before match (lower is better)"
        metricKey="avg_logloss"
        color={COLORS.logloss}
        yLabel="Avg LogLoss"
        domain={(() => {
          const vals = shownBins.map(b => b.avg_logloss).filter(v => v !== null) as number[];
          data?.model_references?.forEach(r => { if (r.avg_logloss !== null) vals.push(r.avg_logloss); });
          if (vals.length === 0) return [0, 1] as [number, number];
          const min = Math.min(...vals);
          const max = Math.max(...vals);
          const pad = (max - min) * 0.15 || 0.05;
          return [Math.max(0, +(min - pad).toFixed(4)), +(max + pad).toFixed(4)] as [number, number];
        })()}
      />

      {/* ─── Chart 3: AUC ────────────────────────────────── */}
      <MetricLineChart
        title="AUC by hours before match (higher is better)"
        metricKey="avg_auc"
        color={COLORS.auc}
        yLabel="Avg AUC"
        domain={[0.4, 1]}
      />

      {/* ─── Model Reference Summary ──────────────────────── */}
      {data.model_references.length > 0 && (
        <div className="model-refs-section">
          <h3>Overall model prediction accuracy</h3>
          <p className="model-refs-subtitle">
            Horizontal dashed lines show each model&apos;s overall LogLoss / AUC across all finished matches.
          </p>
          <div className="model-refs-grid">
            {data.model_references.map(r => {
              const nameLower = r.model_name.toLowerCase();
              let color: string;
              let label: string;
              if (nameLower.includes('thesis') && nameLower.includes('hybrid')) {
                color = '#00d4ff';
                label = 'Hybrid-Thesis-Market';
              } else if (nameLower.includes('thesis') || nameLower.includes('sym-cal')) {
                color = '#ff6b9d';
                label = 'Sym-Cal LR-ElasticNet-W20-Binomial';
              } else if (nameLower.includes('hybrid')) {
                color = '#00e676';
                label = 'Hybrid-PlayerTeam-W20-Market';
              } else {
                color = '#fdd835';
                label = 'Operational-PlayerTeamRatings-W20';
              }
              return (
                <div key={r.model_name} className="model-ref-card">
                  <span className="model-dot" style={{ backgroundColor: color }} />
                  <span className="model-name">{label}</span>
                  <span className="model-metric">LogLoss: {fmt(r.avg_logloss ?? 0)}</span>
                  <span className="model-metric">AUC: {fmt(r.avg_auc ?? 0)}</span>
                  <span className="model-matches">({r.n_matches} matches)</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ─── Bookmaker Results ─────────────────────────────── */}
      {data.bookmaker_bins.length > 0 && (
        <div className="bookmaker-results-section">
          <h3>📊 Per-bookmaker accuracy</h3>
          <p className="bookmaker-results-subtitle">
            Average LogLoss and AUC for each bookmaker across all horizon bins.
            Dashed lines on the charts above correspond to these bookmakers.
          </p>
          <div className="bookmaker-results-grid">
            {data.bookmaker_bins
              .map(bk => {
                // Compute weighted averages across bins
                const binsWithData = bk.bins.filter(b => b.avg_logloss !== null && b.match_count >= minMatches);
                if (binsWithData.length === 0) return null;
                const totalMatches = binsWithData.reduce((s, b) => s + b.match_count, 0);
                const avgLL = binsWithData.reduce((s, b) => s + (b.avg_logloss ?? 0) * b.match_count, 0) / totalMatches;
                const avgAUC = binsWithData.reduce((s, b) => s + (b.avg_auc ?? 0) * b.match_count, 0) / totalMatches;
                const totalSnapshots = binsWithData.reduce((s, b) => s + b.snapshot_count, 0);
                return { ...bk, avgLL, avgAUC, totalMatches, totalSnapshots, binsWithData: binsWithData.length };
              })
              .filter(Boolean)
              .sort((a, b) => (a?.avgLL ?? 999) - (b?.avgLL ?? 999))
              .map((bk, i) => {
                if (!bk) return null;
                // Color matching the chart lines
                const bkColors = [
                  '#8e99a4', '#a3b1bf', '#7c8c9a', '#9ea8b3', '#6b7b8a',
                  '#b0bec5', '#90a4ae', '#78909c', '#607d8b', '#546e7a',
                ];
                const color = bkColors[i % bkColors.length];
                return (
                  <div key={bk.bookmaker_id} className="bookmaker-result-card">
                    <div className="bookmaker-result-header">
                      <span className="bookmaker-result-rank">#{i + 1}</span>
                      <span className="bookmaker-result-dot" style={{ backgroundColor: color }} />
                      <span className="bookmaker-result-name">{bk.bookmaker_name}</span>
                    </div>
                    <div className="bookmaker-result-metrics">
                      <div className="bookmaker-result-metric">
                        <span className="metric-label">LogLoss</span>
                        <span className="metric-value">{bk.avgLL.toFixed(4)}</span>
                      </div>
                      <div className="bookmaker-result-metric">
                        <span className="metric-label">AUC</span>
                        <span className="metric-value">{bk.avgAUC.toFixed(4)}</span>
                      </div>
                      <div className="bookmaker-result-metric">
                        <span className="metric-label">Matches</span>
                        <span className="metric-value">{bk.totalMatches}</span>
                      </div>
                      <div className="bookmaker-result-metric">
                        <span className="metric-label">Snapshots</span>
                        <span className="metric-value">{bk.totalSnapshots}</span>
                      </div>
                    </div>
                    {/* Per-bin breakdown */}
                    <details className="bookmaker-bin-details">
                      <summary>{bk.binsWithData} bins with data</summary>
                      <table>
                        <thead>
                          <tr>
                            <th>Bin</th>
                            <th>Matches</th>
                            <th>LogLoss</th>
                            <th>AUC</th>
                          </tr>
                        </thead>
                        <tbody>
                          {bk.bins
                            .filter(b => b.avg_logloss !== null && b.match_count >= minMatches)
                            .map(b => (
                              <tr key={b.label}>
                                <td>{b.label}</td>
                                <td>{b.match_count}</td>
                                <td>{(b.avg_logloss ?? 0).toFixed(4)}</td>
                                <td>{(b.avg_auc ?? 0).toFixed(4)}</td>
                              </tr>
                            ))}
                        </tbody>
                      </table>
                    </details>
                  </div>
                );
              })}
          </div>
        </div>
      )}

      {/* ─── Legend ──────────────────────────────────────── */}
      <div className="legend-section">
        <h3>Legend</h3>
        <ul>
          <li><strong>LogLoss</strong> — lower = better calibrated predictions. Random guessing = 0.69 (for 50/50).</li>
          <li><strong>AUC</strong> — higher = better discrimination between winners/losers. 0.5 = random, 1.0 = perfect.</li>
          <li>Each point aggregates all pre-match odds snapshots across all bookmakers for finished matches.</li>
          <li>Dashed horizontal lines indicate overall model prediction accuracy (all horizons combined).</li>
          <li>Dashed subtle lines on charts show per-bookmaker accuracy (see table above for details).</li>
          <li>Bins with fewer than {minMatches} matches are hidden but visible in the histogram.</li>
        </ul>
      </div>

      {/* ─── Raw data table ──────────────────────────────── */}
      {allBins.length > 0 && (
        <div className="raw-data">
          <h3>Raw data</h3>
          <table>
            <thead>
              <tr>
                <th>Bin</th>
                <th>Hours</th>
                <th>Snapshots</th>
                <th>Matches</th>
                <th>Avg LogLoss</th>
                <th>Avg AUC</th>
                <th>Avg P(winner)</th>
                <th>Avg P(loser)</th>
              </tr>
            </thead>
            <tbody>
              {allBins.map(b => (
                <tr key={b.label} className={b.match_count < minMatches ? 'row-skipped' : ''}>
                  <td>{b.label}</td>
                  <td>{b.hours_start}–{b.hours_end ?? '∞'}</td>
                  <td>{b.snapshot_count}</td>
                  <td>{b.match_count}</td>
                  <td>{fmt(b.avg_logloss ?? 0)}</td>
                  <td>{fmt(b.avg_auc ?? 0)}</td>
                  <td>{fmt(b.avg_prob_winner ?? 0, 3)}</td>
                  <td>{fmt(b.avg_prob_loser ?? 0, 3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
