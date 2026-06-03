import { useEffect, useState } from 'react';
import { fetchTimingAnalysis } from '../api/client';
import type { TimingAnalysisResponse, TimingBucket } from '../types';
import './TimingAnalysis.css';

const BUCKET_LABELS: Record<string, string> = {
  '48h+': '2+ dni',
  '24-48h': '1-2 dni',
  '12-24h': '12-24h',
  '6-12h': '6-12h',
  '3-6h': '3-6h',
  '1-3h': '1-3h',
  '0-1h': '0-1h',
};

const BUCKET_FULL: Record<string, string> = {
  '48h+': '2+ dni przed meczem',
  '24-48h': '1-2 dni przed meczem',
  '12-24h': '12-24 godz. przed meczem',
  '6-12h': '6-12 godz. przed meczem',
  '3-6h': '3-6 godz. przed meczem',
  '1-3h': '1-3 godz. przed meczem',
  '0-1h': 'Ostatnia godzina przed meczem',
};

const BUCKET_ORDER = ['48h+', '24-48h', '12-24h', '6-12h', '3-6h', '1-3h', '0-1h'];

function fmtOdds(v: number | null | undefined): string {
  if (v == null) return '—';
  return v.toFixed(2);
}

function fmtPct(v: number | null | undefined): string {
  if (v == null) return '—';
  const s = (v * 100).toFixed(1);
  return v > 0 ? `+${s}%` : `${s}%`;
}

function fmtDriftPct(v: number | null | undefined): string {
  if (v == null) return '—';
  return `${(v * 100).toFixed(2)}%`;
}

/** Determine if odds go up (↑), down (↓), or flat (→) from prev bucket */
function trendIcon(current: number, previous: number): string {
  if (previous === 0) return '';
  const diff = ((current - previous) / previous) * 100;
  if (diff > 2) return '↑';
  if (diff < -2) return '↓';
  return '→';
}

/** Returns direction class */
function trendClass(current: number, previous: number): string {
  if (previous === 0) return '';
  const diff = ((current - previous) / previous) * 100;
  if (diff > 2) return 'trend-up';
  if (diff < -2) return 'trend-down';
  return 'trend-flat';
}

// ─── SVG Chart ──────────────────────────────────────────────

function OddsChart({ buckets }: { buckets: TimingBucket[] }) {
  if (!buckets || buckets.length < 2) return null;

  // Sort by time (earliest first: 48h+ → 0-1h)
  const sorted = BUCKET_ORDER
    .map(b => buckets.find(bb => bb.bucket === b))
    .filter((b): b is TimingBucket => b !== undefined);

  const w = 700;
  const h = 300;
  const pad = { top: 30, right: 30, bottom: 50, left: 50 };
  const cw = w - pad.left - pad.right;
  const ch = h - pad.top - pad.bottom;

  // Data range
  const allOdds = sorted.flatMap(b => [b.avg_odds_a, b.avg_odds_b]);
  const minY = Math.floor(Math.min(...allOdds) * 10) / 10 - 0.2;
  const maxY = Math.ceil(Math.max(...allOdds) * 10) / 10 + 0.2;
  const range = maxY - minY || 1;

  const xPos = (i: number) => pad.left + (i / Math.max(sorted.length - 1, 1)) * cw;
  const yPos = (v: number) => pad.top + ch - ((v - minY) / range) * ch;

  // Grid lines
  const gridLines = 5;
  const gridStep = range / gridLines;

  const pathStr = (values: number[]) =>
    values
      .map((v, i) => `${i === 0 ? 'M' : 'L'}${xPos(i).toFixed(0)},${yPos(v).toFixed(0)}`)
      .join(' ');

  return (
    <div className="odds-chart-container">
      <svg viewBox={`0 0 ${w} ${h}`} className="odds-chart" aria-label="Wykres zmian kursów w czasie">
        {/* Grid */}
        {Array.from({ length: gridLines + 1 }, (_, i) => {
          const y = pad.top + (i / gridLines) * ch;
          const val = maxY - i * gridStep;
          return (
            <g key={i}>
              <line x1={pad.left} y1={y} x2={w - pad.right} y2={y} stroke="#2a2a4a" strokeWidth={1} />
              <text x={pad.left - 8} y={y + 4} textAnchor="end" fill="rgba(255,255,255,0.4)" fontSize={11}>
                {val.toFixed(1)}
              </text>
            </g>
          );
        })}

        {/* X-axis labels */}
        {sorted.map((b, i) => (
          <text
            key={b.bucket}
            x={xPos(i)}
            y={h - pad.bottom + 18}
            textAnchor="end"
            transform={`rotate(-35, ${xPos(i)}, ${h - pad.bottom + 18})`}
            fill="rgba(255,255,255,0.6)"
            fontSize={10}
          >
            {BUCKET_LABELS[b.bucket] || b.bucket}
          </text>
        ))}

        {/* Line: Team A */}
        <path
          d={pathStr(sorted.map(b => b.avg_odds_a))}
          fill="none"
          stroke="#4fc3f7"
          strokeWidth={2.5}
          strokeLinejoin="round"
        />

        {/* Line: Team B */}
        <path
          d={pathStr(sorted.map(b => b.avg_odds_b))}
          fill="none"
          stroke="#ff9800"
          strokeWidth={2.5}
          strokeLinejoin="round"
        />

        {/* Data points - Team A */}
        {sorted.map((b, i) => (
          <g key={`a-${i}`}>
            <circle cx={xPos(i)} cy={yPos(b.avg_odds_a)} r={4} fill="#4fc3f7" stroke="#1a1a2e" strokeWidth={1.5} />
            <text
              x={xPos(i)}
              y={yPos(b.avg_odds_a) - 10}
              textAnchor="middle"
              fill="#4fc3f7"
              fontSize={10}
              fontWeight={600}
            >
              {b.avg_odds_a.toFixed(2)}
            </text>
          </g>
        ))}

        {/* Data points - Team B */}
        {sorted.map((b, i) => (
          <g key={`b-${i}`}>
            <circle cx={xPos(i)} cy={yPos(b.avg_odds_b)} r={4} fill="#ff9800" stroke="#1a1a2e" strokeWidth={1.5} />
            <text
              x={xPos(i)}
              y={yPos(b.avg_odds_b) + 16}
              textAnchor="middle"
              fill="#ff9800"
              fontSize={10}
              fontWeight={600}
            >
              {b.avg_odds_b.toFixed(2)}
            </text>
          </g>
        ))}

        {/* Legend */}
        <g transform={`translate(${w - pad.right - 140}, 8)`}>
          <rect x={0} y={0} width={140} height={40} rx={4} fill="#16213e" />
          <line x1={8} y1={16} x2={28} y2={16} stroke="#4fc3f7" strokeWidth={2.5} />
          <text x={34} y={20} fill="rgba(255,255,255,0.8)" fontSize={11}>Średni kurs A</text>
          <line x1={8} y1={34} x2={28} y2={34} stroke="#ff9800" strokeWidth={2.5} />
          <text x={34} y={38} fill="rgba(255,255,255,0.8)" fontSize={11}>Średni kurs B</text>
        </g>
      </svg>

      {/* Y-axis label */}
      <div className="chart-y-label">Kurs</div>

      {/* X-axis label */}
      <div className="chart-x-label">Czas do meczu</div>
    </div>
  );
}

// ─── Component ──────────────────────────────────────────────

export default function TimingAnalysis() {
  const [data, setData] = useState<TimingAnalysisResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [daysBack, setDaysBack] = useState(90);

  useEffect(() => {
    loadData();
  }, [daysBack]);

  async function loadData() {
    try {
      setLoading(true);
      setError(null);
      const result = await fetchTimingAnalysis(daysBack);
      setData(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Nie udało się załadować analizy');
    } finally {
      setLoading(false);
    }
  }

  if (loading) return <div className="loading-text">Ładowanie analizy timingowej…</div>;
  if (error) return <div className="error-text">Błąd: {error}</div>;
  if (!data) return <div className="error-text">Brak danych z API</div>;

  const buckets = data.time_buckets || [];
  // Reverse from API order (0-1h first) to chronological (48h+ first)
  const sortedBuckets = [...buckets].sort(
    (a, b) => BUCKET_ORDER.indexOf(a.bucket) - BUCKET_ORDER.indexOf(b.bucket)
  );

  return (
    <div className="timing-analysis">
      <h1>📈 Kiedy najlepiej obstawiać?</h1>
      <p className="subtitle">
        Analiza zmian kursów w czasie przed meczem na podstawie <strong>{data.total_snapshots}</strong> snapshotów
        z <strong>{data.total_matches}</strong> zakończonych meczów.
      </p>

      {/* Controls */}
      <div className="timing-controls">
        <label>
          Okres:
          <select value={daysBack} onChange={e => setDaysBack(Number(e.target.value))}>
            <option value={7}>7 dni</option>
            <option value={14}>14 dni</option>
            <option value={30}>30 dni</option>
            <option value={60}>60 dni</option>
            <option value={90}>90 dni</option>
          </select>
        </label>
        <button className="btn btn-secondary" onClick={loadData}>⟳ Odśwież</button>
      </div>

      {buckets.length === 0 && (
        <div className="error-text">
          Brak danych do analizy. Zbieramy snapshoty kursów przed meczami — pojawią się, gdy mecze się zakończą.
        </div>
      )}

      {/* ├── MAIN VISUAL ─────────────────────────────── */}
      {buckets.length > 0 && (
        <>
          {/* Spotlight: Best window */}
          {data.best_betting_window && (
            <div className="spotlight-card">
              <div className="spotlight-icon">🎯</div>
              <div className="spotlight-body">
                <div className="spotlight-label">Najlepszy moment na obstawianie</div>
                <div className="spotlight-title">
                  {BUCKET_FULL[data.best_betting_window.bucket] || data.best_betting_window.bucket}
                </div>
                <div className="spotlight-desc">
                  Najniższa zmienność kursów — {data.best_betting_window.recommendation.toLowerCase()}
                </div>
              </div>
              <div className="spotlight-meta">
                <div className="spotlight-stat">
                  <span className="spotlight-stat-value">{fmtOdds(data.best_betting_window.avg_volatility)}</span>
                  <span className="spotlight-stat-label">zmienność σ</span>
                </div>
                <div className="spotlight-stat">
                  <span className="spotlight-stat-value">{data.best_betting_window.sample_size}</span>
                  <span className="spotlight-stat-label">próbki</span>
                </div>
              </div>
            </div>
          )}

          {/* SVG Chart */}
          <section className="section">
            <h2>📊 Jak zmieniają się kursy w czasie?</h2>
            <OddsChart buckets={sortedBuckets} />
          </section>

          {/* Quick stats row */}
          <section className="section">
            <h2>📉 Trendy kursów</h2>
            <div className="trend-grid">
              {sortedBuckets.map((b, i) => {
                const prevA = i > 0 ? sortedBuckets[i - 1].avg_odds_a : 0;
                const prevB = i > 0 ? sortedBuckets[i - 1].avg_odds_b : 0;
                return (
                  <div key={b.bucket} className={`trend-card ${b.bucket === data.best_betting_window?.bucket ? 'trend-best' : ''}`}>
                    <div className="trend-time">{BUCKET_LABELS[b.bucket] || b.bucket}</div>
                    <div className="trend-odds-row">
                      <span className="trend-team-label">Team A</span>
                      <span className={`trend-odds-value ${trendClass(b.avg_odds_a, prevA)}`}>
                        {fmtOdds(b.avg_odds_a)}
                        <span className="trend-icon">{trendIcon(b.avg_odds_a, prevA)}</span>
                      </span>
                    </div>
                    <div className="trend-odds-row">
                      <span className="trend-team-label">Team B</span>
                      <span className={`trend-odds-value ${trendClass(b.avg_odds_b, prevB)}`}>
                        {fmtOdds(b.avg_odds_b)}
                        <span className="trend-icon">{trendIcon(b.avg_odds_b, prevB)}</span>
                      </span>
                    </div>
                    <div className="trend-samples">{b.snapshot_count} snapshotów</div>
                  </div>
                );
              })}
            </div>
          </section>

          {/* Drift Analysis */}
          {data.drift_analysis && (
            <section className="section">
              <h2>🔄 Dryft kursów (wczesne vs późne obstawianie)</h2>
              <p className="section-desc">
                Porównanie średnich kursów z wczesnych snapshotów ({BUCKET_LABELS[data.drift_analysis.early_bucket] || data.drift_analysis.early_bucket})
                i późnych ({BUCKET_LABELS[data.drift_analysis.late_bucket] || data.drift_analysis.late_bucket}).
              </p>
              <div className="drift-grid">
                <div className="drift-card">
                  <div className="drift-label">Dryft kursu A</div>
                  <div className={`drift-value ${data.drift_analysis.drift_odds_a > 0 ? 'positive' : 'negative'}`}>
                    {fmtOdds(data.drift_analysis.drift_odds_a)}
                  </div>
                  <div className="drift-desc">
                    {data.drift_analysis.drift_odds_a > 0
                      ? 'Kursy na Team A rosną bliżej meczu — opłaca się czekać'
                      : 'Kursy na Team A spadają bliżej meczu — lepiej obstawiać wcześniej'}
                  </div>
                </div>
                <div className="drift-card">
                  <div className="drift-label">Dryft kursu B</div>
                  <div className={`drift-value ${data.drift_analysis.drift_odds_b > 0 ? 'positive' : 'negative'}`}>
                    {fmtOdds(data.drift_analysis.drift_odds_b)}
                  </div>
                  <div className="drift-desc">
                    {data.drift_analysis.drift_odds_b > 0
                      ? 'Kursy na Team B rosną bliżej meczu — opłaca się czekać'
                      : 'Kursy na Team B spadają bliżej meczu — lepiej obstawiać wcześniej'}
                  </div>
                </div>
                <div className="drift-card">
                  <div className="drift-label">Interpretacja ogólna</div>
                  <div className="drift-interpretation">{data.drift_analysis.interpretation}</div>
                  <div className="drift-desc">
                    {data.drift_analysis.drift_odds_a < 0 && data.drift_analysis.drift_odds_b < 0
                      ? 'Oba kursy spadają przed meczem → wartość znika z czasem, obstawiaj wcześnie'
                      : data.drift_analysis.drift_odds_a > 0 && data.drift_analysis.drift_odds_b > 0
                      ? 'Oba kursy rosną przed meczem → wartość pojawia się z czasem, poczekaj'
                      : 'Różne kierunki dla Team A i Team B → analizuj każdą stronę osobno'}
                  </div>
                </div>
              </div>
            </section>
          )}

          {/* Summary / insights */}
          <section className="section">
            <h2>💡 Podsumowanie i strategia</h2>
            <ul className="insights-list">
              <li>
                <strong>Zakres danych:</strong> {data.total_matches} meczów, {data.total_snapshots} snapshotów kursów,
                okres {daysBack} dni.
              </li>
              {data.best_betting_window && (
                <li>
                  <strong>Najlepsze okno:</strong> {BUCKET_FULL[data.best_betting_window.bucket]} — najniższa zmienność
                  (σ = {data.best_betting_window.avg_volatility.toFixed(3)}), {data.best_betting_window.sample_size} próbek.
                </li>
              )}
              {data.drift_analysis && (
                <li>
                  <strong>Dryft od wczesnych do późnych:</strong> Kurs A{' '}
                  <span className={data.drift_analysis.drift_odds_a > 0 ? 'positive' : 'negative'}>
                    {fmtDriftPct(data.drift_analysis.drift_odds_a)}
                  </span>
                  , Kurs B{' '}
                  <span className={data.drift_analysis.drift_odds_b > 0 ? 'positive' : 'negative'}>
                    {fmtDriftPct(data.drift_analysis.drift_odds_b)}
                  </span>
                  . {data.drift_analysis.interpretation}
                </li>
              )}
              <li>
                <strong>Źródło:</strong> Dane z wszystkich dostępnych bukmacherów. Wyniki będą się poprawiać
                z każdym kolejnym zakończonym meczem.
              </li>
            </ul>
          </section>

          {/* Full data table (collapsible) */}
          <details className="raw-data-details">
            <summary className="raw-data-summary">📋 Pokaż surowe dane</summary>
            <table className="buckets-table">
              <thead>
                <tr>
                  <th>Okno</th>
                  <th>Team A śr.</th>
                  <th>Team A σ</th>
                  <th>Team A zakres</th>
                  <th>Team B śr.</th>
                  <th>Team B σ</th>
                  <th>Team B zakres</th>
                  <th>Próbki</th>
                </tr>
              </thead>
              <tbody>
                {sortedBuckets.map(b => (
                  <tr key={b.bucket} className={b.bucket === data.best_betting_window?.bucket ? 'best-row' : ''}>
                    <td className="bucket-label">{BUCKET_FULL[b.bucket] || b.bucket}</td>
                    <td>{fmtOdds(b.avg_odds_a)}</td>
                    <td>{fmtOdds(b.std_odds_a)}</td>
                    <td>{fmtOdds(b.min_odds_a)}–{fmtOdds(b.max_odds_a)}</td>
                    <td>{fmtOdds(b.avg_odds_b)}</td>
                    <td>{fmtOdds(b.std_odds_b)}</td>
                    <td>{fmtOdds(b.min_odds_b)}–{fmtOdds(b.max_odds_b)}</td>
                    <td className="sample-count">{b.snapshot_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        </>
      )}
    </div>
  );
}
