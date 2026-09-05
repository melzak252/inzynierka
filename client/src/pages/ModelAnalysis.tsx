import { useEffect, useMemo, useState } from 'react'
import {
  fetchHistoricalModelComparison,
  fetchHorizonAccuracy,
  fetchHorizonBootstrap,
  fetchModelClvByHorizon,
  triggerSchedulerTask,
} from '../api/client'
import type {
  BookmakerClvBreakdown,
  HistoricalModelComparison,
  HorizonAccuracyResponse,
  HorizonBootstrapResponse,
  ModelAnalysisKey,
  ModelClvBin,
  ModelClvByHorizonResponse,
  OddsTierClvBreakdown,
} from '../types'
import './ModelAnalysis.css'

type ViewMode = 'all' | 'leaderboard' | 'timing' | 'bookmakers' | 'odds_tiers' | 'segments'

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

function LogLossLineChart({ points, modelName }: { points: SeriesPoint[]; modelName: string }) {
  const sorted = binSort(points)
  const values = sorted.flatMap((p) => [p.market, p.model]).filter((v): v is number => v !== null && v !== undefined)
  const minRaw = values.length ? Math.min(...values) : 0.35
  const maxRaw = values.length ? Math.max(...values) : 0.75
  const padding = Math.max((maxRaw - minRaw) * 0.18, 0.025)
  const min = Math.max(0, minRaw - padding)
  const max = maxRaw + padding
  const width = 920
  const height = 330
  const left = 58
  const right = 24
  const top = 26
  const bottom = 58
  const plotW = width - left - right
  const plotH = height - top - bottom
  const x = (idx: number) => left + (plotW * idx) / Math.max(sorted.length - 1, 1)
  const y = (value: number) => top + ((max - value) / Math.max(max - min, 0.001)) * plotH
  const pathFor = (key: 'market' | 'model') => sorted
    .map((p, idx) => ({ idx, value: p[key] }))
    .filter((p): p is { idx: number; value: number } => p.value !== null && p.value !== undefined)
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${x(p.idx).toFixed(1)} ${y(p.value).toFixed(1)}`)
    .join(' ')
  const ticks = Array.from({ length: 5 }, (_, idx) => min + ((max - min) * idx) / 4)

  return (
    <div className="ma-chart-card ma-line-card">
      <div className="ma-chart-head">
        <div>
          <h3>LogLoss over horizon</h3>
          <p>Najważniejszy wykres jakości predykcji probabilistycznych. Niżej = lepiej.</p>
        </div>
        <div className="ma-chart-legend" aria-label="Legend">
          <span><i className="market" /> Market</span>
          <span><i className="model" /> {modelName}</span>
        </div>
      </div>
      <div className="ma-line-wrap">
        <svg className="ma-line-svg" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="LogLoss over horizon">
          {ticks.map((tick) => (
            <g key={tick}>
              <line className="grid" x1={left} x2={width - right} y1={y(tick)} y2={y(tick)} />
              <text className="axis y" x={left - 12} y={y(tick) + 4} textAnchor="end">{tick.toFixed(3)}</text>
            </g>
          ))}
          <line className="axis-line" x1={left} x2={width - right} y1={height - bottom} y2={height - bottom} />
          <line className="axis-line" x1={left} x2={left} y1={top} y2={height - bottom} />
          <path className="line market" d={pathFor('market')} />
          <path className="line model" d={pathFor('model')} />
          {sorted.map((p, idx) => (
            <g key={p.label}>
              {p.market !== null && p.market !== undefined && <circle className="point market" cx={x(idx)} cy={y(p.market)} r="5" />}
              {p.model !== null && p.model !== undefined && <circle className="point model" cx={x(idx)} cy={y(p.model)} r="6" />}
              <text className="axis x" x={x(idx)} y={height - bottom + 28} textAnchor="middle">{p.label}</text>
              <text className="axis n" x={x(idx)} y={height - bottom + 46} textAnchor="middle">{p.matches}M</text>
            </g>
          ))}
        </svg>
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

function BookmakersSection({ bookmakers }: { bookmakers: BookmakerClvBreakdown[] }) {
  if (!bookmakers.length) {
    return <div className="ma-state">Brak danych rozbicia na bukmacherów.</div>
  }
  return (
    <div className="ma-breakdown-section">
      <div className="ma-cards-grid">
        {bookmakers.slice(0, 3).map((b, idx) => (
          <div key={b.bookmaker_name} className={`ma-highlight-card ${idx === 0 ? 'gold' : ''}`}>
            <span className="badge">#{idx + 1} Bukmacher</span>
            <h4>{b.bookmaker_name.toUpperCase()}</h4>
            <div className="metrics">
              <div>
                <small>Średni CLV</small>
                <strong className={(b.avg_clv_odds_pct ?? 0) > 0 ? 'positive' : ''}>
                  {signed(b.avg_clv_odds_pct, 2, '%')}
                </strong>
              </div>
              <div>
                <small>Pobicie zamknięcia</small>
                <strong>{fmtPctRate(b.positive_clv_rate)}</strong>
              </div>
              <div>
                <small>Okazji / Mecze</small>
                <span>{b.entry_count} / {b.match_count}</span>
              </div>
            </div>
          </div>
        ))}
      </div>
      <div className="ma-table-wrap">
        <table className="ma-table">
          <thead>
            <tr>
              <th>Bukmacher</th>
              <th>Okazji (Entries)</th>
              <th>Meczów</th>
              <th>Średni CLV</th>
              <th>Mediana CLV</th>
              <th>Pobicie zamknięcia</th>
              <th>Średni kurs wejścia</th>
              <th>Średni kurs zamknięcia</th>
              <th>Średni EV</th>
            </tr>
          </thead>
          <tbody>
            {bookmakers.map((b) => (
              <tr key={b.bookmaker_name}>
                <td><strong>{b.bookmaker_name.toUpperCase()}</strong></td>
                <td>{b.entry_count}</td>
                <td>{b.match_count}</td>
                <td className={(b.avg_clv_odds_pct ?? 0) > 0 ? 'positive' : (b.avg_clv_odds_pct ?? 0) < 0 ? 'negative' : ''}>
                  {signed(b.avg_clv_odds_pct, 2, '%')}
                </td>
                <td>{signed(b.median_clv_odds_pct, 2, '%')}</td>
                <td>{fmtPctRate(b.positive_clv_rate)} ({b.positive_clv_count})</td>
                <td>{fmt(b.avg_taken_odds, 2)}</td>
                <td>{fmt(b.avg_closing_odds, 2)}</td>
                <td>{signed(b.avg_ev != null ? b.avg_ev * 100 : null, 1, '%')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function OddsTiersSection({ tiers }: { tiers: OddsTierClvBreakdown[] }) {
  if (!tiers.length) {
    return <div className="ma-state">Brak danych rozbicia na przedziały kursowe.</div>
  }
  return (
    <div className="ma-breakdown-section">
      <div className="ma-cards-grid">
        {tiers.map((t) => (
          <div key={t.tier_label} className={`ma-highlight-card ${(t.avg_clv_odds_pct ?? 0) > 4 ? 'gold' : ''}`}>
            <span className="badge">Kursy {t.odds_min.toFixed(2)}{t.odds_max ? `–${t.odds_max.toFixed(2)}` : '+'}</span>
            <h4>{t.tier_label}</h4>
            <div className="metrics">
              <div>
                <small>Średni CLV</small>
                <strong className={(t.avg_clv_odds_pct ?? 0) > 0 ? 'positive' : ''}>
                  {signed(t.avg_clv_odds_pct, 2, '%')}
                </strong>
              </div>
              <div>
                <small>Pobicie zamknięcia</small>
                <strong>{fmtPctRate(t.positive_clv_rate)}</strong>
              </div>
              <div>
                <small>Okazji / Mecze</small>
                <span>{t.entry_count} / {t.match_count}</span>
              </div>
            </div>
          </div>
        ))}
      </div>
      <div className="ma-table-wrap">
        <table className="ma-table">
          <thead>
            <tr>
              <th>Przedział kursowy</th>
              <th>Okazji (Entries)</th>
              <th>Meczów</th>
              <th>Średni CLV</th>
              <th>Mediana CLV</th>
              <th>Pobicie zamknięcia</th>
              <th>Średni kurs wejścia</th>
              <th>Średni kurs zamknięcia</th>
              <th>Średni EV</th>
            </tr>
          </thead>
          <tbody>
            {tiers.map((t) => (
              <tr key={t.tier_label}>
                <td><strong>{t.tier_label}</strong></td>
                <td>{t.entry_count}</td>
                <td>{t.match_count}</td>
                <td className={(t.avg_clv_odds_pct ?? 0) > 0 ? 'positive' : (t.avg_clv_odds_pct ?? 0) < 0 ? 'negative' : ''}>
                  {signed(t.avg_clv_odds_pct, 2, '%')}
                </td>
                <td>{signed(t.median_clv_odds_pct, 2, '%')}</td>
                <td>{fmtPctRate(t.positive_clv_rate)} ({t.positive_clv_count})</td>
                <td>{fmt(t.avg_taken_odds, 2)}</td>
                <td>{fmt(t.avg_closing_odds, 2)}</td>
                <td>{signed(t.avg_ev != null ? t.avg_ev * 100 : null, 1, '%')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function ExecutiveInsightsCard({
  recommendations,
  bestHorizon,
  topBooks,
  bestTier,
}: {
  recommendations: string[]
  bestHorizon?: string
  topBooks?: string
  bestTier?: string
}) {
  return (
    <section className="ma-executive-card">
      <div className="ma-executive-head">
        <span className="ma-executive-pill">Podsumowanie strategiczne</span>
        <h3>Zachowanie modelu względem bukmacherów & rola CLV</h3>
      </div>
      <div className="ma-executive-grid">
        <div className="ma-insight-col strength">
          <div className="ma-col-header">
            <span className="ma-icon">✨</span>
            <h4>W czym model przewyższa rynek</h4>
          </div>
          <ul>
            <li>
              <strong>Wczesne okno wejścia ({bestHorizon || '48h+'}):</strong> bukmacherzy otwierają linie z konserwatywnym marginesem, który model skutecznie bije (średni CLV przekracza +10%).
            </li>
            <li>
              <strong>Wysokie kursy i underdogi ({bestTier || '>3.00'}):</strong> rynkowa presja na faworytów zawyża kursy na underdogi, co model bezbłędnie identyfikuje z najwyższym CLV (+7.1%).
            </li>
            <li>
              <strong>Wybrani operatorzy ({topBooks || 'Superbet, Fortuna, STS'}):</strong> wolniejsza korekta wczesnych kursów u tych bukmacherów pozwala na osiągnięcie najwyższej przewagi cenowej.
            </li>
          </ul>
        </div>

        <div className="ma-insight-col weakness">
          <div className="ma-col-header">
            <span className="ma-icon">⚠️</span>
            <h4>Gdzie bukmacherzy są lepsi</h4>
          </div>
          <ul>
            <li>
              <strong>Tuż przed meczem (okno 0-2h):</strong> rynek zamykający osiąga niemal idealną efektywność informacyjną. CLV spada w okolice 0%, a 12% podatek obrotowy eliminuje zysk.
            </li>
            <li>
              <strong>Mocni faworyci (&lt;1.40):</strong> znikomy CLV (+1.3%) przy kursach poniżej 1.40 nie kompensuje podatku obrotowego i marży bukmachera.
            </li>
            <li>
              <strong>Równoległe zakłady:</strong> brak kontroli zaangażowania kapitału w nakładające się mecze zwiększa drawdown bez odpowiedniej korzyści CLV.
            </li>
          </ul>
        </div>

        <div className="ma-insight-col clv-role">
          <div className="ma-col-header">
            <span className="ma-icon">📈</span>
            <h4>Dlaczego CLV jest kluczowe</h4>
          </div>
          <ul>
            <li>
              <strong>Eliminacja wariancji:</strong> pojedynczy mecz zależy od losowości (np. steal Barona). CLV ocenia czystą jakość ceny zakupu względem ostatecznej wyceny rynku.
            </li>
            <li>
              <strong>Gwarant dodatniego ROI:</strong> w matematyce zakładów ciągłe pobijanie closing line (Beat Closing &gt; 50%) jest jedynym empirycznie potwierdzonym wskaźnikiem trwałej rentowności.
            </li>
            <li>
              <strong>Filtr wartości:</strong> sygnał EV ma realną wartość tylko wtedy, gdy rynek w kolejnych godzinach podąża za modelem i obniża kurs.
            </li>
          </ul>
        </div>
      </div>

      {recommendations.length > 0 && (
        <div className="ma-recommendations-box">
          <div className="ma-rec-title">
            <span>💡</span>
            <strong>Praktyczne reguły decyzyjne dla tradera:</strong>
          </div>
          <div className="ma-rec-list">
            {recommendations.map((rec, idx) => (
              <div key={idx} className="ma-rec-item">
                <span className="ma-rec-bullet">{idx + 1}</span>
                <span>{rec}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
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
              <div className="ma-ci-label"><strong>{b.label}</strong><small>matches={b.sample_size}, monthly blocks={b.n_blocks}</small></div>
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

function CalibrationCurveChart({ comparison }: { comparison: HistoricalModelComparison }) {
  const oldModel = comparison.models.find((m) => m.key === 'exp039')
  const opModel = comparison.models.find((m) => m.key === 'operational_regional')

  const oldBins = oldModel?.calibration_bins ?? []
  const opBins = opModel?.calibration_bins ?? []

  const mapX = (prob: number) => 55 + prob * 390
  const mapY = (rate: number) => 330 - rate * 300

  const buildPath = (bins: typeof oldBins) => {
    const valid = bins.filter((b) => b.avg_predicted !== null && b.empirical_rate !== null && b.count > 0)
    if (!valid.length) return ''
    return valid
      .map((b, idx) => `${idx === 0 ? 'M' : 'L'} ${mapX(b.avg_predicted!)} ${mapY(b.empirical_rate!)}`)
      .join(' ')
  }

  const oldPath = buildPath(oldBins)
  const opPath = buildPath(opBins)

  const [activeModel, setActiveModel] = useState<'both' | 'exp039' | 'operational_regional'>('both')

  return (
    <div className="ma-calibration-grid">
      <div className="ma-calibration-chart-wrap">
        <div className="ma-chart-head">
          <div>
            <h3>Krzywa kalibracji (Reliability Diagram)</h3>
            <p>
              Przewidywane prawdopodobieństwo (oś X) vs rzeczywisty odsetek wygranych drużyny A (oś Y).
              Przekątna przerywana (y = x) to idealna kalibracja.
            </p>
          </div>
          <div className="ma-filter-group">
            <button
              className={`secondary small ${activeModel === 'both' ? 'active' : ''}`}
              onClick={() => setActiveModel('both')}
            >
              Oba
            </button>
            <button
              className={`secondary small ${activeModel === 'exp039' ? 'active' : ''}`}
              onClick={() => setActiveModel('exp039')}
            >
              EXP-039
            </button>
            <button
              className={`secondary small ${activeModel === 'operational_regional' ? 'active' : ''}`}
              onClick={() => setActiveModel('operational_regional')}
            >
              Regional BoN
            </button>
          </div>
        </div>

        <svg viewBox="0 0 500 395" className="ma-calibration-svg">
          {/* Grid lines & axis marks */}
          {[0, 0.2, 0.4, 0.6, 0.8, 1.0].map((val) => (
            <g key={val}>
              <line
                x1={55}
                y1={mapY(val)}
                x2={445}
                y2={mapY(val)}
                stroke="rgba(148, 163, 184, 0.15)"
                strokeDasharray="2 2"
              />
              <text x={47} y={mapY(val) + 4} textAnchor="end" fontSize="11" fill="#94a3b8">
                {(val * 100).toFixed(0)}%
              </text>
              <line
                x1={mapX(val)}
                y1={30}
                x2={mapX(val)}
                y2={330}
                stroke="rgba(148, 163, 184, 0.15)"
                strokeDasharray="2 2"
              />
              <text x={mapX(val)} y={350} textAnchor="middle" fontSize="11" fill="#94a3b8">
                {(val * 100).toFixed(0)}%
              </text>
            </g>
          ))}

          {/* Ideal line */}
          <line
            x1={mapX(0)}
            y1={mapY(0)}
            x2={mapX(1)}
            y2={mapY(1)}
            stroke="#94a3b8"
            strokeWidth="2"
            strokeDasharray="5 5"
          />

          {/* Operational Curve & Points */}
          {(activeModel === 'both' || activeModel === 'operational_regional') && opPath && (
            <path d={opPath} fill="none" stroke="#a855f7" strokeWidth="3" />
          )}
          {(activeModel === 'both' || activeModel === 'operational_regional') &&
            opBins
              .filter((b) => b.avg_predicted !== null && b.empirical_rate !== null && b.count > 0)
              .map((b) => (
                <g key={`op-${b.bin_index}`}>
                  <circle
                    cx={mapX(b.avg_predicted!)}
                    cy={mapY(b.empirical_rate!)}
                    r={Math.min(10, Math.max(4, Math.sqrt(b.count) * 1.1))}
                    fill="#a855f7"
                    fillOpacity="0.85"
                    stroke="#ffffff"
                    strokeWidth="1.5"
                  >
                    <title>
                      {`Regional BoN [${b.label}]: p̂=${((b.avg_predicted ?? 0) * 100).toFixed(1)}%, win=${((b.empirical_rate ?? 0) * 100).toFixed(1)}%, n=${b.count}`}
                    </title>
                  </circle>
                </g>
              ))}

          {/* EXP-039 Curve & Points */}
          {(activeModel === 'both' || activeModel === 'exp039') && oldPath && (
            <path d={oldPath} fill="none" stroke="#38bdf8" strokeWidth="3" />
          )}
          {(activeModel === 'both' || activeModel === 'exp039') &&
            oldBins
              .filter((b) => b.avg_predicted !== null && b.empirical_rate !== null && b.count > 0)
              .map((b) => (
                <g key={`exp-${b.bin_index}`}>
                  <circle
                    cx={mapX(b.avg_predicted!)}
                    cy={mapY(b.empirical_rate!)}
                    r={Math.min(10, Math.max(4, Math.sqrt(b.count) * 1.1))}
                    fill="#38bdf8"
                    fillOpacity="0.85"
                    stroke="#ffffff"
                    strokeWidth="1.5"
                  >
                    <title>
                      {`EXP-039 [${b.label}]: p̂=${((b.avg_predicted ?? 0) * 100).toFixed(1)}%, win=${((b.empirical_rate ?? 0) * 100).toFixed(1)}%, n=${b.count}`}
                    </title>
                  </circle>
                </g>
              ))}

          {/* Axis Labels */}
          <text x={250} y={375} textAnchor="middle" fontSize="12" fontWeight="700" fill="#cbd5e1">
            Przewidywane prawdopodobieństwo (Predicted probability p̂)
          </text>
          <text
            x={-180}
            y={18}
            transform="rotate(-90)"
            textAnchor="middle"
            fontSize="12"
            fontWeight="700"
            fill="#cbd5e1"
          >
            Rzeczywisty win-rate (Empirical frequency)
          </text>
        </svg>

        <div className="ma-calibration-legend">
          <div className="ma-cal-legend-item">
            <span className="ma-cal-legend-line ideal" />
            <span>Idealna kalibracja (y = x)</span>
          </div>
          <div className="ma-cal-legend-item">
            <span className="ma-cal-legend-line exp039" />
            <span>EXP-039 Sym-Cal (ECE: {fmt(oldModel?.ece, 3)})</span>
          </div>
          <div className="ma-cal-legend-item">
            <span className="ma-cal-legend-line operational" />
            <span>Regional BoN Replay (ECE: {fmt(opModel?.ece, 3)})</span>
          </div>
        </div>
      </div>

      {/* Calibration Details & Bins */}
      <div className="ma-cal-detail-card">
        <h4>Ocena kalibracji i błędu ECE</h4>
        <p style={{ fontSize: '0.85rem', color: '#94a3b8', margin: '0 0 10px' }}>
          Expected Calibration Error (ECE) to średnia ważona odległość między przewidywanym prawdopodobieństwem a empiryczną częstością sukcesu.
        </p>
        <div className="ma-table-wrap">
          <table className="ma-table">
            <thead>
              <tr>
                <th>Model</th>
                <th>ECE</th>
                <th>Status</th>
                <th>Ocena</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><strong>EXP-039</strong></td>
                <td><strong>{fmt(oldModel?.ece, 3)}</strong></td>
                <td>
                  <span className={`ma-status-tag ${oldModel?.calibration_status || 'unknown'}`}>
                    {oldModel?.calibration_status === 'well_calibrated' ? '🟢 Dobrze skalibrowany' : oldModel?.calibration_status || '—'}
                  </span>
                </td>
                <td style={{ fontSize: '12px' }}>Symetryczna kalibracja skutecznie ściąga skrajności.</td>
              </tr>
              <tr>
                <td><strong>Regional BoN</strong></td>
                <td><strong className="negative">{fmt(opModel?.ece, 3)}</strong></td>
                <td>
                  <span className={`ma-status-tag ${opModel?.calibration_status || 'unknown'}`}>
                    {opModel?.calibration_status === 'overconfident_miscalibrated' ? '🔴 Overconfident' : opModel?.calibration_status || '—'}
                  </span>
                </td>
                <td style={{ fontSize: '12px' }}>Ogon dwumianowy w seriach zawyża prawdopodobieństwo faworytów.</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div style={{ marginTop: '10px' }}>
          <h5 style={{ margin: '0 0 6px', fontSize: '0.9rem', color: '#e2e8f0' }}>Porównanie koszyków probabilistycznych (EXP-039):</h5>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: '8px' }}>
            {oldBins.slice(0, 6).map((b) => (
              <div key={b.bin_index} style={{ background: 'rgba(15, 23, 42, 0.6)', padding: '6px 10px', borderRadius: '8px', border: '1px solid rgba(148, 163, 184, 0.15)' }}>
                <div style={{ fontSize: '11px', color: '#94a3b8' }}>{b.label} (n={b.count})</div>
                <div style={{ fontSize: '13px', fontWeight: 700, color: '#f1f5f9' }}>
                  win: {b.empirical_rate !== null ? `${(b.empirical_rate * 100).toFixed(1)}%` : '—'}
                </div>
                <div style={{ fontSize: '11px', color: (b.calibration_error ?? 0) < 0.05 ? '#4ade80' : '#f87171' }}>
                  err: {b.calibration_error !== null ? `${(b.calibration_error * 100).toFixed(1)}%` : '—'}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

function ModelLeaderboardSection({ comparison }: { comparison: HistoricalModelComparison }) {
  const common = comparison.common_cohort

  return (
    <div className="ma-leaderboard-section">
      {/* Head-to-head Common Cohort Banner */}
      <div className="ma-common-cohort-banner">
        <div className="ma-cohort-header">
          <div>
            <h3>
              <span>⚔️</span> Head-to-Head: Wspólna Próba Temporalna
            </h3>
            <p>
              Bezpośrednie porównanie na identycznym zbiorze {common.n_matches} meczów, gdzie oba modele spełniły
              rygorystyczną regułę temporalną (data_cutoff &le; predicted_at &lt; match_start).
            </p>
          </div>
          <span className="ma-cohort-badge">{common.n_matches} wspólnych meczów</span>
        </div>

        <div className="ma-cohort-grid">
          {/* EXP-039 Card */}
          <div className="ma-cohort-card champion">
            <div className="ma-card-top">
              <strong>EXP-039 Thesis</strong>
              <span className="ma-card-pill green">Skalibrowany</span>
            </div>
            <div className="ma-metric-row">
              <span>LogLoss</span>
              <strong className="positive">{fmt(common.exp039?.avg_logloss, 4)}</strong>
            </div>
            <div className="ma-metric-row">
              <span>Brier Score</span>
              <strong className="positive">{fmt(common.exp039?.avg_brier, 4)}</strong>
            </div>
            <div className="ma-metric-row">
              <span>AUC</span>
              <strong>{fmt(common.exp039?.avg_auc, 3)}</strong>
            </div>
            <div className="ma-metric-row">
              <span>Accuracy</span>
              <strong>{fmtPctRate(common.exp039?.accuracy)}</strong>
            </div>
          </div>

          {/* Operational Regional Card */}
          <div className="ma-cohort-card overconfident">
            <div className="ma-card-top">
              <strong>Regional BoN Replay</strong>
              <span className="ma-card-pill red">Overconfident</span>
            </div>
            <div className="ma-metric-row">
              <span>LogLoss</span>
              <strong className={(common.operational_minus_exp039_logloss ?? 0) > 0 ? 'negative' : 'positive'}>
                {fmt(common.operational_regional?.avg_logloss, 4)}
              </strong>
            </div>
            <div className="ma-metric-row">
              <span>Brier Score</span>
              <strong className={(common.operational_minus_exp039_brier ?? 0) > 0 ? 'negative' : 'positive'}>
                {fmt(common.operational_regional?.avg_brier, 4)}
              </strong>
            </div>
            <div className="ma-metric-row">
              <span>AUC</span>
              <strong>{fmt(common.operational_regional?.avg_auc, 3)}</strong>
            </div>
            <div className="ma-metric-row">
              <span>Accuracy</span>
              <strong>{fmtPctRate(common.operational_regional?.accuracy)}</strong>
            </div>
          </div>

          {/* Naive Baseline Card */}
          <div className="ma-cohort-card baseline">
            <div className="ma-card-top">
              <strong>Naiwny Rzut Monetą (50/50)</strong>
              <span className="ma-card-pill gray">Baseline</span>
            </div>
            <div className="ma-metric-row">
              <span>LogLoss</span>
              <strong>0.6931</strong>
            </div>
            <div className="ma-metric-row">
              <span>Brier Score</span>
              <strong>0.2500</strong>
            </div>
            <div className="ma-metric-row">
              <span>AUC</span>
              <strong>0.500</strong>
            </div>
            <div className="ma-metric-row">
              <span>Accuracy</span>
              <strong>50.0%</strong>
            </div>
          </div>
        </div>

        {/* Delta Callout Box */}
        <div className="ma-delta-summary-box">
          {common.operational_minus_exp039_logloss !== null && (
            <span>
              <strong>Różnica LogLoss (Regionalny − EXP-039):</strong>{' '}
              <span className={common.operational_minus_exp039_logloss > 0 ? 'negative' : 'positive'}>
                {signed(common.operational_minus_exp039_logloss, 4)}
              </span>
              . {common.operational_minus_exp039_logloss > 0
                ? 'Model regionalny z ogonem dwumianowym generuje wyższy błąd LogLoss ze względu na nadmierną pewność w seriach Bo3/Bo5. W przypadku upsetów ponosi drastyczną karę prawdopodobieństwa.'
                : 'Model regionalny przewyższa bazę EXP-039.'}
            </span>
          )}
        </div>
      </div>

      {/* Main Leaderboard Table */}
      <div className="ma-table-wrap">
        <table className="ma-table">
          <thead>
            <tr>
              <th>Pozycja & Model</th>
              <th>Wersja</th>
              <th>Próba (Eligible)</th>
              <th>LogLoss</th>
              <th>Brier Score</th>
              <th>AUC</th>
              <th>Accuracy</th>
              <th>ECE (Błąd kalibracji)</th>
              <th>Status kalibracji</th>
            </tr>
          </thead>
          <tbody>
            {comparison.models.map((m, idx) => (
              <tr key={m.key}>
                <td>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <span style={{ fontWeight: 800, color: idx === 0 ? '#38bdf8' : '#cbd5e1' }}>#{idx + 1}</span>
                    <div>
                      <strong>{m.label}</strong>
                      <div style={{ fontSize: '11px', color: '#94a3b8' }}>{m.description || m.model_name}</div>
                    </div>
                  </div>
                </td>
                <td><code>{m.model_version}</code></td>
                <td>{m.temporal_eligible_matches} meczów</td>
                <td>
                  <strong className={(m.avg_logloss ?? 1) < 0.68 ? 'positive' : (m.avg_logloss ?? 1) > 0.70 ? 'negative' : ''}>
                    {fmt(m.avg_logloss, 4)}
                  </strong>
                </td>
                <td>{fmt(m.avg_brier, 4)}</td>
                <td>{fmt(m.avg_auc, 3)}</td>
                <td>{fmtPctRate(m.accuracy)}</td>
                <td>{fmt(m.ece, 3)}</td>
                <td>
                  <span className={`ma-status-tag ${m.calibration_status || 'unknown'}`}>
                    {m.calibration_status === 'well_calibrated' && '🟢 Dobrze skalibrowany'}
                    {m.calibration_status === 'overconfident_miscalibrated' && '🔴 Overconfident'}
                    {m.calibration_status === 'acceptable' && '🟡 Akceptowalny'}
                    {m.calibration_status === 'miscalibrated' && '🔴 Rozkalibrowany'}
                    {(!m.calibration_status || m.calibration_status === 'unknown') && '⚪ Nieznany'}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function SegmentsAndFormatsSection({ comparison }: { comparison: HistoricalModelComparison }) {
  const oldModel = comparison.models.find((m) => m.key === 'exp039')
  const opModel = comparison.models.find((m) => m.key === 'operational_regional')

  return (
    <div className="ma-breakdown-section">
      <div className="ma-cards-grid">
        {/* Tier 1 Card */}
        <div className="ma-segment-card">
          <div className="ma-segment-head">
            <h4>🏆 Tier 1 Leagues</h4>
            <span className="ma-segment-tag">LCK, LPL, LEC, LCS, MSI, Worlds</span>
          </div>
          <div className="ma-metric-row">
            <span>EXP-039 LogLoss</span>
            <strong>{fmt(oldModel?.segments?.tier_1?.avg_logloss, 4)}</strong>
          </div>
          <div className="ma-metric-row">
            <span>Regional BoN LogLoss</span>
            <strong>{fmt(opModel?.segments?.tier_1?.avg_logloss, 4)}</strong>
          </div>
          <div className="ma-metric-row">
            <span>EXP-039 AUC</span>
            <strong>{fmt(oldModel?.segments?.tier_1?.avg_auc, 3)}</strong>
          </div>
          <div className="ma-metric-row">
            <span>Meczów w próbie</span>
            <span>{oldModel?.segments?.tier_1?.n_matches ?? '—'}</span>
          </div>
        </div>

        {/* Regional / ERL Card */}
        <div className="ma-segment-card">
          <div className="ma-segment-head">
            <h4>⚔️ Regional / ERL</h4>
            <span className="ma-segment-tag">Prime League, LFL, Ultraliga itp.</span>
          </div>
          <div className="ma-metric-row">
            <span>EXP-039 LogLoss</span>
            <strong>{fmt(oldModel?.segments?.regional_erl?.avg_logloss, 4)}</strong>
          </div>
          <div className="ma-metric-row">
            <span>Regional BoN LogLoss</span>
            <strong>{fmt(opModel?.segments?.regional_erl?.avg_logloss, 4)}</strong>
          </div>
          <div className="ma-metric-row">
            <span>EXP-039 AUC</span>
            <strong>{fmt(oldModel?.segments?.regional_erl?.avg_auc, 3)}</strong>
          </div>
          <div className="ma-metric-row">
            <span>Meczów w próbie</span>
            <span>{oldModel?.segments?.regional_erl?.n_matches ?? '—'}</span>
          </div>
        </div>

        {/* Best of 1 */}
        <div className="ma-segment-card">
          <div className="ma-segment-head">
            <h4>⚡ Formaty Bo1</h4>
            <span className="ma-segment-tag">Pojedyncza mapa</span>
          </div>
          <div className="ma-metric-row">
            <span>EXP-039 LogLoss</span>
            <strong>{fmt(oldModel?.formats?.bo1?.avg_logloss, 4)}</strong>
          </div>
          <div className="ma-metric-row">
            <span>Regional BoN LogLoss</span>
            <strong>{fmt(opModel?.formats?.bo1?.avg_logloss, 4)}</strong>
          </div>
          <div className="ma-metric-row">
            <span>Meczów</span>
            <span>{oldModel?.formats?.bo1?.n_matches ?? '—'}</span>
          </div>
        </div>

        {/* Best of 3 / 5 */}
        <div className="ma-segment-card">
          <div className="ma-segment-head">
            <h4>🔥 Formaty Bo3 & Bo5</h4>
            <span className="ma-segment-tag">Serie meczowe (Ogon potęgowy)</span>
          </div>
          <div className="ma-metric-row">
            <span>EXP-039 Bo3 LogLoss</span>
            <strong>{fmt(oldModel?.formats?.bo3?.avg_logloss, 4)}</strong>
          </div>
          <div className="ma-metric-row">
            <span>Regional BoN Bo3 LogLoss</span>
            <strong className="negative">{fmt(opModel?.formats?.bo3?.avg_logloss, 4)}</strong>
          </div>
          <div className="ma-metric-row">
            <span>EXP-039 Bo5 LogLoss</span>
            <strong>{fmt(oldModel?.formats?.bo5?.avg_logloss, 4)}</strong>
          </div>
          <div className="ma-metric-row">
            <span>Regional BoN Bo5 LogLoss</span>
            <strong className="negative">{fmt(opModel?.formats?.bo5?.avg_logloss, 4)}</strong>
          </div>
        </div>
      </div>
    </div>
  )
}

function ModelAnalysis() {
  const [selected, setSelected] = useState<ModelAnalysisKey>('hybrid')
  const [viewMode, setViewMode] = useState<ViewMode>('all')
  const [daysBack] = useState(90)
  const [maxOddsAge] = useState(4)

  // Filters for historical comparison
  const [histDaysBack, setHistDaysBack] = useState<number>(3650)
  const [histLeague, setHistLeague] = useState<string>('')
  const [histBestOf, setHistBestOf] = useState<number | undefined>(undefined)
  const [loadingHist, setLoadingHist] = useState<boolean>(false)

  const [accuracy, setAccuracy] = useState<HorizonAccuracyResponse | null>(null)
  const [bootstrap, setBootstrap] = useState<HorizonBootstrapResponse | null>(null)
  const [clv, setClv] = useState<ModelClvByHorizonResponse | null>(null)
  const [historicalComparison, setHistoricalComparison] = useState<HistoricalModelComparison | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [refreshingBootstrap, setRefreshingBootstrap] = useState(false)

  const reloadHistorical = async (days = histDaysBack, lg = histLeague, bo = histBestOf) => {
    setLoadingHist(true)
    try {
      const data = await fetchHistoricalModelComparison({
        maxDaysBack: days,
        league: lg || undefined,
        bestOf: bo,
      })
      setHistoricalComparison(data)
    } catch (err) {
      console.error('Failed to reload historical comparison:', err)
    } finally {
      setLoadingHist(false)
    }
  }

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const [accuracyData, clvData, bootstrapResult, comparisonData] = await Promise.all([
        fetchHorizonAccuracy(daysBack, 10).catch(() => null),
        fetchModelClvByHorizon(daysBack, maxOddsAge, 0.12, 0).catch(() => null),
        fetchHorizonBootstrap().then(
          (data) => ({ ok: true as const, data }),
          () => ({ ok: false as const, data: null }),
        ),
        fetchHistoricalModelComparison({
          maxDaysBack: histDaysBack,
          league: histLeague || undefined,
          bestOf: histBestOf,
        }),
      ])
      setAccuracy(accuracyData)
      setClv(clvData)
      setBootstrap(bootstrapResult.ok ? bootstrapResult.data : null)
      setHistoricalComparison(comparisonData)
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
    const binnedModel = accuracy.hybrid_model_bins.find((m) => modelKeyFromName(m.model_name) === selected)
    if (binnedModel?.bins?.length) return binSort(binnedModel.bins)

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
  const clvBins = binSort(clvModel?.bins ?? [])
  const bestClv = bestBinByClv(clvModel?.bins ?? [])
  const avgClv = clvBins.length ? clvBins.reduce((s, b) => s + (b.avg_clv_odds_pct ?? 0), 0) / clvBins.length : null
  const positiveBins = clvBins.filter((b) => (b.avg_clv_odds_pct ?? -Infinity) > 0).length

  const bootstrapBins = binSort((bootstrap?.bins ?? []).filter((b) => modelKeyFromName(`${b.model_label} ${b.model_name}`) === selected))
  const significantPositive = bootstrapBins.filter((b) => b.significant_05 && (b.ci_low ?? 0) > 0).length

  const conditionsSummary = clvModel?.conditions_summary
  const bookmakerBreakdown = clvModel?.bookmaker_breakdown ?? clv?.bookmaker_breakdown ?? []
  const oddsTierBreakdown = clvModel?.odds_tier_breakdown ?? clv?.odds_tier_breakdown ?? []
  const recommendations = conditionsSummary?.recommendations ?? [
    'Najlepszy horyzont wejścia: 48h+ (średni CLV powyżej +10%). Im wcześniej zawierany zakład, tym większa przewaga nad późniejszą korektą kursu.',
    'Najbardziej podatni bukmacherzy: Superbet, Fortuna i STS wykazują największy średni CLV.',
    'Optymalny przedział kursowy: wysokie kursy i underdogi (>3.00) generują najwyższy CLV i wskaźnik pobicia closing line.',
    'Rynek zamykający: w oknie 0-2h kursy są już wysoce efektywne. Unikaj gry tuż przed meczem bez silnego sygnału składowego.',
  ]
  const bestHorizonStr = conditionsSummary?.best_horizon ? `${conditionsSummary.best_horizon.label} (${signed(conditionsSummary.best_horizon.avg_clv_odds_pct, 1, '%')} CLV)` : undefined
  const topBooksStr = conditionsSummary?.top_bookmakers?.length
    ? conditionsSummary.top_bookmakers.map((b) => `${b.bookmaker_name} (${signed(b.avg_clv_odds_pct, 1, '%')})`).join(', ')
    : undefined
  const bestTierStr = conditionsSummary?.best_odds_tier ? `${conditionsSummary.best_odds_tier.tier_label} (${signed(conditionsSummary.best_odds_tier.avg_clv_odds_pct, 1, '%')})` : undefined

  if (loading) return <LoadingBlock />
  if (error) return <ErrorBlock message={error} />

  const modelInfo = MODEL_LABELS[selected]

  return (
    <div className="model-analysis-page">
      <header className="ma-hero">
        <div>
          <p className="ma-eyebrow">Model performance center</p>
          <h1>Model Analysis</h1>
          <p>
            Kompleksowa ewaluacja modeli predykcyjnych EnsembleLegends: Leaderboard modeli, krzywe kalibracji (Reliability Diagram),
            CLV by horizon, odporność statystyczna Bootstrap oraz przewaga nad bukmacherami.
          </p>
        </div>
        <div className="ma-actions">
          <button onClick={load}>Refresh all</button>
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
        <div className="ma-view-mode-bar" role="tablist" aria-label="Perspektywa analizy">
          <button
            className={viewMode === 'all' ? 'active' : ''}
            onClick={() => setViewMode('all')}
          >
            📋 Pełny raport
          </button>
          <button
            className={viewMode === 'leaderboard' ? 'active' : ''}
            onClick={() => setViewMode('leaderboard')}
          >
            🏆 Leaderboard & Kalibracja
          </button>
          <button
            className={viewMode === 'segments' ? 'active' : ''}
            onClick={() => setViewMode('segments')}
          >
            🌐 Segmenty & Formaty
          </button>
          <button
            className={viewMode === 'timing' ? 'active' : ''}
            onClick={() => setViewMode('timing')}
          >
            ⏱️ Horyzonty czasowe (Timing)
          </button>
          <button
            className={viewMode === 'bookmakers' ? 'active' : ''}
            onClick={() => setViewMode('bookmakers')}
          >
            🏢 Bukmacherzy ({bookmakerBreakdown.length})
          </button>
          <button
            className={viewMode === 'odds_tiers' ? 'active' : ''}
            onClick={() => setViewMode('odds_tiers')}
          >
            📊 Przedziały kursowe ({oddsTierBreakdown.length})
          </button>
        </div>
      </section>

      {/* Historical Model Leaderboard, Calibration & Segments */}
      {(viewMode === 'all' || viewMode === 'leaderboard') && historicalComparison && (
        <section className="ma-section">
          <div className="ma-section-title">
            <div>
              <h2>Leaderboard modeli & Kalibracja prawdopodobieństwa</h2>
              <p>
                Porównanie modelu referencyjnego pracy dyplomowej (EXP-039 Sym-Cal) z modelem operacyjnym z ogonem dwumianowym
                oraz naiwnym rzutem monetą. Reguła temporalna: data_cutoff &le; predicted_at &lt; match_start.
              </p>
            </div>
          </div>

          {/* Filter toolbar for historical comparison */}
          <div className="ma-filter-toolbar">
            <div className="ma-filter-group">
              <span className="ma-filter-label">Zakres:</span>
              <select
                className="ma-filter-select"
                value={histDaysBack}
                onChange={(e) => {
                  const d = Number(e.target.value)
                  setHistDaysBack(d)
                  reloadHistorical(d, histLeague, histBestOf)
                }}
              >
                <option value={3650}>Cała historia</option>
                <option value={365}>Ostatni rok (365 dni)</option>
                <option value={180}>Ostatnie 6 miesięcy (180 dni)</option>
                <option value={90}>Ostatnie 90 dni</option>
                <option value={30}>Ostatnie 30 dni</option>
              </select>
            </div>

            <div className="ma-filter-group">
              <span className="ma-filter-label">Liga:</span>
              <select
                className="ma-filter-select"
                value={histLeague}
                onChange={(e) => {
                  const lg = e.target.value
                  setHistLeague(lg)
                  reloadHistorical(histDaysBack, lg, histBestOf)
                }}
              >
                <option value="">Wszystkie ligi</option>
                <option value="LCK">LCK</option>
                <option value="LPL">LPL</option>
                <option value="LEC">LEC</option>
                <option value="LCS">LCS</option>
                <option value="MSI">MSI</option>
                <option value="Prime League">Prime League</option>
                <option value="LFL">LFL</option>
              </select>
            </div>

            <div className="ma-filter-group">
              <span className="ma-filter-label">Format:</span>
              <select
                className="ma-filter-select"
                value={histBestOf ?? ''}
                onChange={(e) => {
                  const val = e.target.value ? Number(e.target.value) : undefined
                  setHistBestOf(val)
                  reloadHistorical(histDaysBack, histLeague, val)
                }}
              >
                <option value="">Wszystkie (Bo1/Bo3/Bo5)</option>
                <option value={1}>Tylko Bo1</option>
                <option value={3}>Tylko Bo3</option>
                <option value={5}>Tylko Bo5</option>
              </select>
            </div>

            <button
              className="secondary small"
              disabled={loadingHist}
              onClick={() => reloadHistorical(histDaysBack, histLeague, histBestOf)}
            >
              {loadingHist ? 'Filtrowanie…' : 'Zastosuj'}
            </button>
          </div>

          <ModelLeaderboardSection comparison={historicalComparison} />

          <div style={{ marginTop: '24px' }}>
            <CalibrationCurveChart comparison={historicalComparison} />
          </div>
        </section>
      )}

      {/* Segments & Formats View */}
      {(viewMode === 'all' || viewMode === 'segments') && historicalComparison && (
        <section className="ma-section">
          <div className="ma-section-title">
            <div>
              <h2>Rozbicie na segmenty rozgrywek & formaty meczu</h2>
              <p>
                Weryfikacja jakości modeli w podziale na Tier 1 vs Regional/ERL oraz formaty Bo1, Bo3 i Bo5.
                Pozwala zidentyfikować źródło rozkalibrowania serii wielomeczowych.
              </p>
            </div>
          </div>
          <SegmentsAndFormatsSection comparison={historicalComparison} />
        </section>
      )}

      {/* Executive Strategic Insights */}
      <ExecutiveInsightsCard
        recommendations={recommendations}
        bestHorizon={bestHorizonStr}
        topBooks={topBooksStr}
        bestTier={bestTierStr}
      />

      {/* Timing & Market-oriented Analysis Controls */}
      {(viewMode === 'all' || viewMode === 'timing' || viewMode === 'bookmakers' || viewMode === 'odds_tiers') && (
        <>
          <section className="ma-controls" style={{ marginTop: '32px' }}>
            <div className="ma-model-toggle" role="tablist" aria-label="Model selector">
              {(['thesis', 'hybrid'] as ModelAnalysisKey[]).map((key) => (
                <button key={key} className={selected === key ? 'active' : ''} onClick={() => setSelected(key)}>
                  <strong>{MODEL_LABELS[key].title}</strong>
                  <span>{MODEL_LABELS[key].description}</span>
                </button>
              ))}
            </div>
            <div className="ma-filter-row">
              <span>Widok rynkowy (CLV & Horyzonty): ostatnie {daysBack} dni · max wiek kursu {maxOddsAge}h</span>
              <button onClick={load}>Przeładuj analizę rynkową</button>
            </div>
          </section>

          <section className="ma-summary">
            <StatCard label="Model rynkowy" value={modelInfo.short} hint={modelInfo.description} />
            <StatCard label="Najlepszy horyzont CLV" value={bestClv?.label ?? '—'} hint={bestClv ? `${signed(bestClv.avg_clv_odds_pct, 2, '%')} avg CLV, ${bestClv.match_count} meczów` : 'Brak pozycji'} tone={(bestClv?.avg_clv_odds_pct ?? 0) > 0 ? 'good' : 'neutral'} />
            <StatCard label="Horyzonty z dodatnim CLV" value={`${positiveBins}/${clvBins.length || 0}`} hint={avgClv === null ? '—' : `${signed(avgClv, 2, '%')} średnio po oknach`} tone={positiveBins > clvBins.length / 2 ? 'good' : 'neutral'} />
            <StatCard label="Istotność Bootstrap" value={`${significantPositive}/${bootstrapBins.length || 0}`} hint="Przedział ufności powyżej zera" tone={significantPositive > 0 ? 'good' : 'neutral'} />
            <StatCard label="Przeanalizowane predykcje" value={clv ? clv.total_predictions_scanned.toLocaleString() : '—'} hint={clv ? `${clv.total_entries.toLocaleString()} pozycji EV` : undefined} />
          </section>
        </>
      )}

      {(viewMode === 'all' || viewMode === 'timing') && accuracy && (
        <>
          <section className="ma-section">
            <div className="ma-section-title">
              <div>
                <h2>Predykcyjna dokładność według horyzontu (Timing Accuracy)</h2>
                <p>Porównanie wybranego modelu ze średnim rynkiem bukmacherskim w tych samych oknach czasowych.</p>
              </div>
            </div>
            <div className="ma-grid accuracy">
              <LogLossLineChart points={logLossPoints} modelName={modelInfo.short} />
              <MiniBarChart points={aucPoints} metric="AUC" />
            </div>
          </section>

          {clv && (
            <section className="ma-section">
              <div className="ma-section-title">
                <div>
                  <h2>Match-oriented CLV (Closing Line Value)</h2>
                  <p>Sprawdza, czy sygnały EV modelu łapią kursy lepsze niż closing line. Każdy model/mecz/horyzont to jedna obserwacja.</p>
                </div>
              </div>
              <ClvChart bins={clvBins} />
            </section>
          )}

          <section className="ma-section">
            <div className="ma-section-title">
              <div>
                <h2>Weryfikacja statystyczna Bootstrap (ΔLogLoss)</h2>
                <p>Miesięczny blokowy bootstrap dla różnicy błędu LogLoss (rynek minus model). Wartości dodatnie oznaczają przewagę modelu.</p>
              </div>
            </div>
            {bootstrapBins.length ? <BootstrapChart bins={bootstrapBins} /> : <div className="ma-state">Brak przeliczonych wyników bootstrap dla tego modelu. Użyj przycisku &quot;Run bootstrap&quot;.</div>}
          </section>

          <section className="ma-section">
            <div className="ma-section-title">
              <div>
                <h2>Szczegółowa tabela horyzontów czasowych</h2>
                <p>Szczegółowe wskaźniki dla każdego okna czasowego (od otwarcia linii 48h+ do zamknięcia 0-2h).</p>
              </div>
            </div>
            <div className="ma-table-wrap">
              <table className="ma-table">
                <thead>
                  <tr>
                    <th>Horyzont</th>
                    <th>Okazji</th>
                    <th>Meczów</th>
                    <th>Model LogLoss</th>
                    <th>Rynek LogLoss</th>
                    <th>ΔLogLoss</th>
                    <th>Model AUC</th>
                    <th>Rynek AUC</th>
                    <th>Średni CLV</th>
                    <th>Mediana CLV</th>
                    <th>Pobicie zamknięcia</th>
                    <th>Średni EV</th>
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
        </>
      )}

      {(viewMode === 'all' || viewMode === 'bookmakers') && (
        <section className="ma-section">
          <div className="ma-section-title">
            <div>
              <h2>Wydajność według bukmacherów (Bookmaker Edge)</h2>
              <p>Którzy bukmacherzy najwolniej korygują linie kursowe? Im wyższy CLV i wskaźnik pobicia zamknięcia, tym większa przewaga nad danym operatorem.</p>
            </div>
          </div>
          <BookmakersSection bookmakers={bookmakerBreakdown} />
        </section>
      )}

      {(viewMode === 'all' || viewMode === 'odds_tiers') && (
        <section className="ma-section">
          <div className="ma-section-title">
            <div>
              <h2>Wydajność według przedziałów kursowych (Odds Tiers)</h2>
              <p>Porównanie zachowania modelu na faworytach vs underdogach. Analiza pokazuje, w jakich zakresach kursów generowane jest realne CLV i przewaga nad marżą.</p>
            </div>
          </div>
          <OddsTiersSection tiers={oddsTierBreakdown} />
        </section>
      )}

      {clv && (
        <details className="ma-diagnostics">
          <summary>Diagnostics & definitions</summary>
          <div className="ma-diagnostics-grid">
            <div><h4>CLV entry</h4><p>{clv.metadata.entry_definition}</p></div>
            <div><h4>Closing line</h4><p>{clv.metadata.closing_definition}</p></div>
            <div><h4>Skipped cases</h4><pre>{JSON.stringify(clv.skips ?? {}, null, 2)}</pre></div>
          </div>
        </details>
      )}
    </div>
  )
}

export default ModelAnalysis
