import { useEffect, useMemo, useState } from 'react'
import {
  fetchHorizonAccuracy,
  fetchHorizonBootstrap,
  fetchModelClvByHorizon,
  triggerSchedulerTask,
} from '../api/client'
import type {
  HorizonAccuracyResponse,
  HorizonBootstrapResponse,
  ModelAnalysisKey,
  ModelClvBin,
  ModelClvByHorizonResponse,
} from '../types'
import './ModelAnalysis.css'

type Weighting = 'match' | 'signal'

type SeriesPoint = {
  label: string
  market: number | null
  model: number | null
  matches: number
  entries?: number
}

const MODEL_LABELS: Record<ModelAnalysisKey, { title: string; short: string; description: string; accent: string }> = {
  thesis: {
    title: 'Thesis model',
    short: 'Thesis',
    description: 'Czysty model predykcyjny bez domieszki prawdopodobieństwa rynkowego.',
    accent: '#2563eb',
  },
  hybrid: {
    title: 'Hybrid model',
    short: 'Hybrid',
    description: 'Połączenie Twojego modelu z informacją rynkową/kursami.',
    accent: '#7c3aed',
  },
}

const HORIZON_ORDER = ['0-2h', '2-6h', '6-12h', '12-24h', '24-48h', '48h+']

function fmt(value: number | null | undefined, digits = 2, suffix = ''): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return `${value.toFixed(digits)}${suffix}`
}

function fmtPctRate(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return `${(value * 100).toFixed(1)}%`
}

function fmtP(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  if (value < 0.001) return '<0.001'
  return value.toFixed(3)
}

function signed(value: number | null | undefined, digits = 2, suffix = ''): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return `${value >= 0 ? '+' : ''}${value.toFixed(digits)}${suffix}`
}

function binSort<T extends { label: string }>(rows: T[]): T[] {
  return [...rows].sort((a, b) => HORIZON_ORDER.indexOf(a.label) - HORIZON_ORDER.indexOf(b.label))
}

function modelKeyFromName(name: string): ModelAnalysisKey {
  return name.toLowerCase().includes('hybrid') ? 'hybrid' : 'thesis'
}

function bestBinByClv(bins: ModelClvBin[]): ModelClvBin | null {
  const valid = bins.filter((b) => b.avg_clv_odds_pct !== null && b.match_count > 0)
  if (!valid.length) return null
  return valid.reduce((best, b) => (b.avg_clv_odds_pct! > best.avg_clv_odds_pct! ? b : best), valid[0])
}

function StatCard({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: 'good' | 'bad' | 'neutral' }) {
  return (
    <div className={`ma-stat-card ${tone || 'neutral'}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      {hint && <small>{hint}</small>}
    </div>
  )
}

function LoadingBlock() {
  return <div className="ma-state">Ładowanie analizy modelu…</div>
}

function ErrorBlock({ message }: { message: string }) {
  return <div className="ma-state error">{message}</div>
}

function MiniBarChart({ points, metric, lowerIsBetter }: { points: SeriesPoint[]; metric: string; lowerIsBetter?: boolean }) {
  const values = points.flatMap((p) => [p.market, p.model]).filter((v): v is number => v !== null && v !== undefined)
  const min = values.length ? Math.min(...values) : 0
  const max = values.length ? Math.max(...values) : 1
  const span = Math.max(max - min, 0.001)

  return (
    <div className="ma-chart-card">
      <div className="ma-chart-head">
        <h3>{metric}</h3>
        <p>{lowerIsBetter ? 'Niżej = lepiej' : 'Wyżej = lepiej'} · model vs średni rynek</p>
      </div>
      <div className="ma-bars">
        {points.map((p) => {
          const marketWidth = p.market === null ? 0 : 8 + ((p.market - min) / span) * 82
          const modelWidth = p.model === null ? 0 : 8 + ((p.model - min) / span) * 82
          return (
            <div className="ma-bar-row" key={p.label}>
              <div className="ma-bar-label">
                <strong>{p.label}</strong>
                <small>{p.matches} meczów</small>
              </div>
              <div className="ma-bar-lines">
                <div className="ma-bar-line">
                  <span>Market</span>
                  <div className="ma-bar-track"><div className="ma-bar market" style={{ width: `${marketWidth}%` }} /></div>
                  <b>{fmt(p.market, 3)}</b>
                </div>
                <div className="ma-bar-line">
                  <span>Model</span>
                  <div className="ma-bar-track"><div className="ma-bar model" style={{ width: `${modelWidth}%` }} /></div>
                  <b>{fmt(p.model, 3)}</b>
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function ClvChart({ bins }: { bins: ModelClvBin[] }) {
  const sorted = binSort(bins)
  const values = sorted.map((b) => b.avg_clv_odds_pct ?? 0)
  const maxAbs = Math.max(1, ...values.map((v) => Math.abs(v)))
  return (
    <div className="ma-chart-card clv">
      <div className="ma-chart-head">
        <h3>CLV by horizon</h3>
        <p>CLV = entry odds / closing odds − 1. Dodatni CLV oznacza, że model złapał lepszy kurs niż zamknięcie.</p>
      </div>
      <div className="ma-clv-chart">
        <div className="ma-zero-line" />
        {sorted.map((b) => {
          const v = b.avg_clv_odds_pct ?? 0
          const height = Math.max(3, Math.abs(v) / maxAbs * 110)
          return (
            <div className="ma-clv-col" key={b.label}>
              <div className="ma-clv-plot">
                <div
                  className={`ma-clv-bar ${v >= 0 ? 'positive' : 'negative'}`}
                  style={{ height: `${height}px`, [v >= 0 ? 'bottom' : 'top']: '50%' }}
                />
              </div>
              <strong>{signed(b.avg_clv_odds_pct, 2, '%')}</strong>
              <span>{b.label}</span>
              <small>{b.match_count}M / {b.entry_count}E</small>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function BootstrapChart({ bins }: { bins: HorizonBootstrapResponse['bins'] }) {
  const sorted = binSort(bins)
  const values = sorted.flatMap((b) => [b.ci_low, b.ci_high, b.observed_difference]).filter((v): v is number => v !== null && v !== undefined)
  const maxAbs = Math.max(0.01, ...values.map((v) => Math.abs(v)))
  return (
    <div className="ma-chart-card">
      <div className="ma-chart-head">
        <h3>Bootstrap ΔLogLoss</h3>
        <p>ΔLogLoss = market LogLoss − model LogLoss. Powyżej zera model jest lepszy od rynku.</p>
      </div>
      <div className="ma-ci-list">
        {sorted.map((b) => {
          const left = 50 + ((b.ci_low ?? 0) / maxAbs) * 45
          const right = 50 + ((b.ci_high ?? 0) / maxAbs) * 45
          const point = 50 + ((b.observed_difference ?? 0) / maxAbs) * 45
          const tone = b.significant_05 && (b.ci_low ?? 0) > 0 ? 'good' : b.significant_05 && (b.ci_high ?? 0) < 0 ? 'bad' : 'neutral'
          return (
            <div className="ma-ci-row" key={`${b.model_label}-${b.label}`}>
              <div className="ma-ci-label"><strong>{b.label}</strong><small>n={b.sample_size}, blocks={b.n_blocks}</small></div>
              <div className="ma-ci-track">
                <div className="ma-ci-zero" />
                <div className={`ma-ci-range ${tone}`} style={{ left: `${Math.min(left, right)}%`, width: `${Math.abs(right - left)}%` }} />
                <div className={`ma-ci-point ${tone}`} style={{ left: `${point}%` }} />
              </div>
              <div className="ma-ci-value">
                <strong>{signed(b.observed_difference, 4)}</strong>
                <small>p={fmtP(b.p_one_sided)}</small>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function ModelAnalysis() {
  const [selected, setSelected] = useState<ModelAnalysisKey>('hybrid')
  const [weighting, setWeighting] = useState<Weighting>('match')
  const [daysBack, setDaysBack] = useState(90)
  const [maxOddsAge, setMaxOddsAge] = useState(4)
  const [accuracy, setAccuracy] = useState<HorizonAccuracyResponse | null>(null)
  const [bootstrap, setBootstrap] = useState<HorizonBootstrapResponse | null>(null)
  const [clv, setClv] = useState<ModelClvByHorizonResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [refreshingBootstrap, setRefreshingBootstrap] = useState(false)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const [accuracyData, clvData, bootstrapResult] = await Promise.all([
        fetchHorizonAccuracy(daysBack, 10),
        fetchModelClvByHorizon(daysBack, maxOddsAge, 0.12, 0),
        fetchHorizonBootstrap().then(
          (data) => ({ ok: true as const, data }),
          () => ({ ok: false as const, data: null }),
        ),
      ])
      setAccuracy(accuracyData)
      setClv(clvData)
      setBootstrap(bootstrapResult.ok ? bootstrapResult.data : null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Nie udało się pobrać danych analizy')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const selectedModelBins = useMemo(() => {
    if (!accuracy) return []
    if (selected === 'hybrid') {
      const hybrid = accuracy.hybrid_model_bins.find((m) => modelKeyFromName(m.model_name) === 'hybrid')
      return binSort(hybrid?.bins ?? [])
    }
    const ref = accuracy.model_references.find((m) => modelKeyFromName(m.model_name) === 'thesis')
    return binSort(accuracy.bins.map((b) => ({
      label: b.label,
      hours_start: b.hours_start,
      hours_end: b.hours_end,
      snapshot_count: b.snapshot_count,
      match_count: ref?.n_matches ?? b.match_count,
      avg_logloss: ref?.avg_logloss ?? null,
      avg_auc: ref?.avg_auc ?? null,
    })))
  }, [accuracy, selected])

  const marketBins = useMemo(() => binSort(accuracy?.bins ?? []), [accuracy])

  const logLossPoints: SeriesPoint[] = useMemo(() => marketBins.map((market) => {
    const model = selectedModelBins.find((b) => b.label === market.label)
    return { label: market.label, market: market.avg_logloss, model: model?.avg_logloss ?? null, matches: model?.match_count ?? market.match_count }
  }), [marketBins, selectedModelBins])

  const aucPoints: SeriesPoint[] = useMemo(() => marketBins.map((market) => {
    const model = selectedModelBins.find((b) => b.label === market.label)
    return { label: market.label, market: market.avg_auc, model: model?.avg_auc ?? null, matches: model?.match_count ?? market.match_count }
  }), [marketBins, selectedModelBins])

  const clvModel = clv?.models.find((m) => m.model_key === selected)
  const clvBins = binSort((weighting === 'match' ? clvModel?.match_weighted_bins : clvModel?.signal_weighted_bins) ?? [])
  const bestClv = bestBinByClv(clvModel?.match_weighted_bins ?? [])
  const avgClv = clvBins.length ? clvBins.reduce((s, b) => s + (b.avg_clv_odds_pct ?? 0), 0) / clvBins.length : null
  const positiveBins = clvBins.filter((b) => (b.avg_clv_odds_pct ?? -Infinity) > 0).length

  const bootstrapBins = binSort((bootstrap?.bins ?? []).filter((b) => modelKeyFromName(`${b.model_label} ${b.model_name}`) === selected))
  const significantPositive = bootstrapBins.filter((b) => b.significant_05 && (b.ci_low ?? 0) > 0).length

  if (loading) return <LoadingBlock />
  if (error) return <ErrorBlock message={error} />

  const modelInfo = MODEL_LABELS[selected]

  return (
    <div className="model-analysis-page">
      <header className="ma-hero">
        <div>
          <p className="ma-eyebrow">Model performance center</p>
          <h1>Model Analysis</h1>
          <p>Jedna strona do oceny, czy Twój model pokonuje rynek: accuracy, CLV, bootstrap i szczegółowe tabele po horyzoncie czasowym.</p>
        </div>
        <div className="ma-actions">
          <button onClick={load}>Refresh</button>
          <button
            className="secondary"
            disabled={refreshingBootstrap}
            onClick={async () => {
              setRefreshingBootstrap(true)
              try { await triggerSchedulerTask('horizon_bootstrap') } finally { setRefreshingBootstrap(false) }
            }}
          >
            {refreshingBootstrap ? 'Running…' : 'Run bootstrap'}
          </button>
        </div>
      </header>

      <section className="ma-controls">
        <div className="ma-model-toggle" role="tablist" aria-label="Model selector">
          {(['thesis', 'hybrid'] as ModelAnalysisKey[]).map((key) => (
            <button key={key} className={selected === key ? 'active' : ''} onClick={() => setSelected(key)}>
              <strong>{MODEL_LABELS[key].title}</strong>
              <span>{MODEL_LABELS[key].description}</span>
            </button>
          ))}
        </div>
        <div className="ma-filter-row">
          <label>Days back <input type="number" value={daysBack} min={7} max={365} onChange={(e) => setDaysBack(Number(e.target.value))} /></label>
          <label>Max odds age <input type="number" value={maxOddsAge} min={0.5} max={48} step={0.5} onChange={(e) => setMaxOddsAge(Number(e.target.value))} /></label>
          <button onClick={load}>Apply filters</button>
        </div>
      </section>

      <section className="ma-summary">
        <StatCard label="Selected model" value={modelInfo.short} hint={modelInfo.description} />
        <StatCard label="Best CLV horizon" value={bestClv?.label ?? '—'} hint={bestClv ? `${signed(bestClv.avg_clv_odds_pct, 2, '%')} avg CLV, ${bestClv.match_count} matches` : 'No CLV entries'} tone={(bestClv?.avg_clv_odds_pct ?? 0) > 0 ? 'good' : 'neutral'} />
        <StatCard label="Positive CLV bins" value={`${positiveBins}/${clvBins.length || 0}`} hint={avgClv === null ? '—' : `${signed(avgClv, 2, '%')} avg across bins`} tone={positiveBins > clvBins.length / 2 ? 'good' : 'neutral'} />
        <StatCard label="Bootstrap significant" value={`${significantPositive}/${bootstrapBins.length || 0}`} hint="CI entirely above zero" tone={significantPositive > 0 ? 'good' : 'neutral'} />
        <StatCard label="Data scanned" value={clv ? clv.total_predictions_scanned.toLocaleString() : '—'} hint={clv ? `${clv.total_entries.toLocaleString()} EV entries` : undefined} />
      </section>

      <section className="ma-section">
        <div className="ma-section-title">
          <div><h2>Predictive accuracy by horizon</h2><p>Porównanie wybranego modelu ze średnim rynkiem bukmacherskim w tych samych horyzontach.</p></div>
        </div>
        <div className="ma-grid two">
          <MiniBarChart points={logLossPoints} metric="LogLoss" lowerIsBetter />
          <MiniBarChart points={aucPoints} metric="AUC" />
        </div>
      </section>

      <section className="ma-section">
        <div className="ma-section-title">
          <div><h2>Market timing / CLV</h2><p>Sprawdza, czy sygnały EV modelu łapią kursy lepsze niż closing line.</p></div>
          <div className="ma-pill-toggle">
            <button className={weighting === 'match' ? 'active' : ''} onClick={() => setWeighting('match')}>Match-weighted</button>
            <button className={weighting === 'signal' ? 'active' : ''} onClick={() => setWeighting('signal')}>Signal-weighted</button>
          </div>
        </div>
        <ClvChart bins={clvBins} />
      </section>

      <section className="ma-section">
        <div className="ma-section-title">
          <div><h2>Statistical validation</h2><p>Bootstrap blokowy po miesiącach dla ΔLogLoss modelu względem benchmarku rynkowego.</p></div>
        </div>
        {bootstrapBins.length ? <BootstrapChart bins={bootstrapBins} /> : <div className="ma-state">Brak wyników bootstrap dla wybranego modelu.</div>}
      </section>

      <section className="ma-section">
        <div className="ma-section-title">
          <div><h2>Detailed horizon table</h2><p>Pełne liczby dla aktualnie wybranego modelu i sposobu ważenia CLV.</p></div>
        </div>
        <div className="ma-table-wrap">
          <table className="ma-table">
            <thead>
              <tr>
                <th>Horizon</th><th>Entries</th><th>Matches</th><th>Model LogLoss</th><th>Market LogLoss</th><th>ΔLogLoss</th><th>Model AUC</th><th>Market AUC</th><th>Avg CLV</th><th>Median CLV</th><th>Positive CLV</th><th>Avg EV</th>
              </tr>
            </thead>
            <tbody>
              {HORIZON_ORDER.map((label) => {
                const market = marketBins.find((b) => b.label === label)
                const model = selectedModelBins.find((b) => b.label === label)
                const c = clvBins.find((b) => b.label === label)
                const deltaLogLoss = market?.avg_logloss != null && model?.avg_logloss != null ? market.avg_logloss - model.avg_logloss : null
                return (
                  <tr key={label}>
                    <td><strong>{label}</strong></td>
                    <td>{c?.entry_count ?? '—'}</td>
                    <td>{c?.match_count ?? model?.match_count ?? market?.match_count ?? '—'}</td>
                    <td>{fmt(model?.avg_logloss, 4)}</td>
                    <td>{fmt(market?.avg_logloss, 4)}</td>
                    <td className={(deltaLogLoss ?? 0) > 0 ? 'positive' : (deltaLogLoss ?? 0) < 0 ? 'negative' : ''}>{signed(deltaLogLoss, 4)}</td>
                    <td>{fmt(model?.avg_auc, 3)}</td>
                    <td>{fmt(market?.avg_auc, 3)}</td>
                    <td className={(c?.avg_clv_odds_pct ?? 0) > 0 ? 'positive' : (c?.avg_clv_odds_pct ?? 0) < 0 ? 'negative' : ''}>{signed(c?.avg_clv_odds_pct, 2, '%')}</td>
                    <td>{signed(c?.median_clv_odds_pct, 2, '%')}</td>
                    <td>{fmtPctRate(c?.positive_clv_rate)}</td>
                    <td>{signed(c?.avg_ev != null ? c.avg_ev * 100 : null, 1, '%')}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </section>

      <details className="ma-diagnostics">
        <summary>Diagnostics & definitions</summary>
        <div className="ma-diagnostics-grid">
          <div><h4>CLV entry</h4><p>{clv?.metadata.entry_definition}</p></div>
          <div><h4>Closing line</h4><p>{clv?.metadata.closing_definition}</p></div>
          <div><h4>Skipped cases</h4><pre>{JSON.stringify(clv?.skips ?? {}, null, 2)}</pre></div>
        </div>
      </details>
    </div>
  )
}

export default ModelAnalysis
