import { useEffect, useState } from 'react';
import { fetchTimingAnalysis } from '../api/client';
import type { TimingAnalysisResponse, TimingBucket, DriftAnalysis } from '../types';
import './TimingAnalysis.css';

export default function TimingAnalysis() {
  const [data, setData] = useState<TimingAnalysisResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [daysBack, setDaysBack] = useState(30);

  useEffect(() => {
    loadData();
  }, [daysBack]);

  async function loadData() {
    try {
      setLoading(true);
      const result = await fetchTimingAnalysis(daysBack);
      setData(result);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load timing analysis');
    } finally {
      setLoading(false);
    }
  }

  function formatOdds(value: number | null | undefined): string {
    if (value == null) return '—';
    return value.toFixed(2);
  }

  function formatPercent(value: number | null | undefined): string {
    if (value == null) return '—';
    return `${(value * 100).toFixed(1)}%`;
  }

  function getBucketLabel(bucket: string): string {
    const labels: Record<string, string> = {
      '0-1h': '0–1 godz. przed meczem',
      '1-3h': '1–3 godz. przed meczem',
      '3-6h': '3–6 godz. przed meczem',
      '6-12h': '6–12 godz. przed meczem',
      '12-24h': '12–24 godz. przed meczem',
      '24-48h': '1–2 dni przed meczem',
      '48h+': '2+ dni przed meczem',
    };
    return labels[bucket] || bucket;
  }

  if (loading) return <div className="loading">Ładowanie analizy timingowej...</div>;
  if (error) return <div className="error">Błąd: {error}</div>;
  if (!data) return <div className="error">Brak danych</div>;

  return (
    <div className="timing-analysis">
      <h1>Analiza Timingowa — Kiedy obstawiać?</h1>
      <p className="subtitle">
        Jak zmieniają się kursy w zależności od czasu do meczu. Dane z ostatnich{' '}
        <strong>{daysBack}</strong> dni.
      </p>

      <div className="controls">
        <label>
          Zakres dni:
          <select value={daysBack} onChange={(e) => setDaysBack(Number(e.target.value))}>
            <option value={7}>7 dni</option>
            <option value={14}>14 dni</option>
            <option value={30}>30 dni</option>
            <option value={60}>60 dni</option>
            <option value={90}>90 dni</option>
          </select>
        </label>
        <button onClick={loadData} className="btn btn-secondary">
          Odśwież
        </button>
      </div>

      {/* Best Betting Window */}
      {data.best_window && (
        <section className="best-window">
          <h2>🎯 Rekomendowane okno do obstawiania</h2>
          <div className="best-window-card">
            <div className="best-window-label">
              {getBucketLabel(data.best_window.window)}
            </div>
            <div className="best-window-reason">{data.best_window.reason}</div>
            <div className="best-window-stats">
              <div>
                <span className="stat-label">Średni kurs:</span>{' '}
                <span className="stat-value">{formatOdds(data.best_window.avg_odds)}</span>
              </div>
              <div>
                <span className="stat-label">Średni EV:</span>{' '}
                <span className="stat-value">{formatPercent(data.best_window.avg_ev)}</span>
              </div>
              <div>
                <span className="stat-label">Liczba próbek:</span>{' '}
                <span className="stat-value">{data.best_window.sample_count}</span>
              </div>
            </div>
          </div>
        </section>
      )}

      {/* Odds by Time Bucket */}
      <section className="buckets-section">
        <h2>📊 Kursy w zależności od czasu do meczu</h2>
        <div className="buckets-table-wrapper">
          <table className="buckets-table">
            <thead>
              <tr>
                <th>Okno czasowe</th>
                <th>Średni kurs</th>
                <th>Std Dev</th>
                <th>Min</th>
                <th>Max</th>
                <th>Próbki</th>
              </tr>
            </thead>
            <tbody>
              {data.buckets.map((bucket: TimingBucket) => (
                <tr key={bucket.window}>
                  <td className="bucket-label">{getBucketLabel(bucket.window)}</td>
                  <td>{formatOdds(bucket.avg_odds)}</td>
                  <td>{formatOdds(bucket.std_odds)}</td>
                  <td>{formatOdds(bucket.min_odds)}</td>
                  <td>{formatOdds(bucket.max_odds)}</td>
                  <td>{bucket.sample_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Drift Analysis */}
      {data.drift_analysis && data.drift_analysis.length > 0 && (
        <section className="drift-section">
          <h2>📈 Analiza dryftu kursów (wczesne vs późne)</h2>
          <p className="section-description">
            Porównanie średnich kursów z okna wczesnego (24h+) i późnego (&lt;6h) przed meczem.
            Dodatni dryft oznacza, że kursy rosną bliżej meczu.
          </p>
          <div className="drift-grid">
            {data.drift_analysis.map((drift: DriftAnalysis) => (
              <div key={drift.bookmaker} className="drift-card">
                <h3>{drift.bookmaker}</h3>
                <div className="drift-stats">
                  <div>
                    <span className="stat-label">Wczesny śr.:</span>{' '}
                    <span className="stat-value">{formatOdds(drift.early_avg)}</span>
                  </div>
                  <div>
                    <span className="stat-label">Późny śr.:</span>{' '}
                    <span className="stat-value">{formatOdds(drift.late_avg)}</span>
                  </div>
                  <div>
                    <span className="stat-label">Dryft:</span>{' '}
                    <span
                      className={`stat-value ${
                        drift.drift_percent > 0
                          ? 'positive'
                          : drift.drift_percent < 0
                          ? 'negative'
                          : ''
                      }`}
                    >
                      {formatPercent(drift.drift_percent)}
                    </span>
                  </div>
                  <div>
                    <span className="stat-label">Kierunek:</span>{' '}
                    <span className="stat-value">
                      {drift.drift_percent > 0.01
                        ? '↑ Kursy rosną'
                        : drift.drift_percent < -0.01
                        ? '↓ Kursy maleją'
                        : '→ Stabilne'}
                    </span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Summary / Insights */}
      <section className="insights-section">
        <h2>💡 Wnioski</h2>
        <div className="insights-card">
          <ul>
            {data.buckets.length > 0 && (
              <li>
                Najwięcej próbek zebrano w oknie{' '}
                <strong>
                  {getBucketLabel(
                    data.buckets.reduce((a, b) =>
                      a.sample_count > b.sample_count ? a : b
                    ).window
                  )}
                </strong>
                .
              </li>
            )}
            {data.best_window && (
              <li>
                Najlepsze okno do obstawiania to{' '}
                <strong>{getBucketLabel(data.best_window.window)}</strong> —{' '}
                {data.best_window.reason}
              </li>
            )}
            {data.drift_analysis && data.drift_analysis.length > 0 && (
              <li>
                Średni dryft kursów:{' '}
                <strong>
                  {formatPercent(
                    data.drift_analysis.reduce((sum, d) => sum + d.drift_percent, 0) /
                      data.drift_analysis.length
                  )}
                </strong>
                .
              </li>
            )}
          </ul>
        </div>
      </section>
    </div>
  );
}
