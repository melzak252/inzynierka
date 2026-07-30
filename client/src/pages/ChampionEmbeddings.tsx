import { useEffect, useMemo, useState } from 'react'
import { fetchChampionEmbeddings } from '../api/client'
import type { ChampionEmbeddingPoint, ChampionEmbeddingProjectionResponse } from '../types'
import './ChampionEmbeddings.css'

const ROLE_COLORS: Record<string, string> = {
  TOP: '#f97316',
  JUNGLE: '#22c55e',
  MID: '#a855f7',
  ADC: '#38bdf8',
  SUPPORT: '#facc15',
}

type ProjectionMethod = 'umap' | 'tsne' | 'pca'

type ProjectionControls = {
  method: ProjectionMethod
  snapshot: string
  role: string
  minGames: number
}

function pct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return `${(value * 100).toFixed(digits)}%`
}

function num(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return value.toFixed(digits)
}

function pointRadius(point: ChampionEmbeddingPoint): number {
  const games = point.n_games ?? 0
  return Math.max(4, Math.min(12, 4 + Math.log10(games + 1) * 3.2))
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="ce-stat">
      <span>{label}</span>
      <strong>{value}</strong>
      {hint && <small>{hint}</small>}
    </div>
  )
}

function Tooltip({ point }: { point: ChampionEmbeddingPoint }) {
  return (
    <div className="ce-tooltip-card">
      <div className="ce-tooltip-title">
        <span className="ce-role-dot" style={{ background: ROLE_COLORS[point.role || ''] || '#94a3b8' }} />
        <strong>{point.champion_name}</strong>
        <small>{point.role}</small>
      </div>
      <dl>
        <dt>Gry</dt><dd>{num(point.n_games, 0)}</dd>
        <dt>Win rate</dt><dd>{pct(point.win_rate)}</dd>
        <dt>KDA</dt><dd>{num(point.kda)}</dd>
        <dt>KP</dt><dd>{pct(point.kill_participation)}</dd>
        <dt>Damage share</dt><dd>{pct(point.damage_share)}</dd>
        <dt>Gold share</dt><dd>{pct(point.gold_share)}</dd>
        <dt>Fallback</dt><dd>{point.fallback_level || '—'}</dd>
        <dt>Shrinkage</dt><dd>{pct(point.shrinkage_weight_observed)}</dd>
      </dl>
    </div>
  )
}

export default function ChampionEmbeddings() {
  const [draftControls, setDraftControls] = useState<ProjectionControls>({
    method: 'umap',
    snapshot: 'latest',
    role: 'ALL',
    minGames: 0,
  })
  const [appliedControls, setAppliedControls] = useState<ProjectionControls>(draftControls)
  const [query, setQuery] = useState('')
  const [data, setData] = useState<ChampionEmbeddingProjectionResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<ChampionEmbeddingPoint | null>(null)
  const [hovered, setHovered] = useState<ChampionEmbeddingPoint | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    let cancelled = false
    async function load() {
      try {
        setLoading(true)
        const result = await fetchChampionEmbeddings(
          appliedControls.method,
          appliedControls.role,
          appliedControls.minGames,
          appliedControls.snapshot,
          controller.signal,
        )
        if (!cancelled) {
          setData(result)
          setError(null)
          setSelected(null)
          setHovered(null)
        }
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') return
        if (!cancelled) setError(err instanceof Error ? err.message : 'Nie udało się pobrać embeddingów championów')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
      controller.abort()
    }
  }, [appliedControls])

  const roles = data?.metadata.available_roles?.length ? ['ALL', ...data.metadata.available_roles] : ['ALL', 'TOP', 'JUNGLE', 'MID', 'ADC', 'SUPPORT']
  const snapshots = data?.metadata.available_snapshots?.length ? data.metadata.available_snapshots : []
  const visiblePoints = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!data) return []
    if (!q) return data.points
    return data.points.filter((p) => p.champion_name.toLowerCase().includes(q) || p.champion_id.includes(q))
  }, [data, query])

  const activePoint = hovered || selected
  const roleCounts = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const p of data?.points ?? []) counts[p.role || 'UNKNOWN'] = (counts[p.role || 'UNKNOWN'] || 0) + 1
    return counts
  }, [data])
  const controlsDirty =
    draftControls.method !== appliedControls.method ||
    draftControls.snapshot !== appliedControls.snapshot ||
    draftControls.role !== appliedControls.role ||
    draftControls.minGames !== appliedControls.minGames

  const applyControls = () => {
    setAppliedControls({
      ...draftControls,
      minGames: Math.max(0, Math.min(1000, Number(draftControls.minGames) || 0)),
    })
  }

  return (
    <div className="ce-page">
      <header className="ce-header">
        <div>
          <p className="ce-kicker">Embedding diagnostics</p>
          <h1>Champion embeddings</h1>
          <p>
            Interaktywna mapa 2D pokazująca walk-forward embeddingi championów per rola
            z artefaktu EXP-056. Punkt = para <strong>champion + role</strong>, liczona tylko z gier sprzed wybranej daty.
          </p>
        </div>
      </header>

      <section className="ce-controls">
        <label>
          Projekcja
          <select
            value={draftControls.method}
            onChange={(e) => setDraftControls((prev) => ({ ...prev, method: e.target.value as ProjectionMethod }))}
          >
            <option value="umap">UMAP</option>
            <option value="tsne">t-SNE</option>
            <option value="pca">PCA</option>
          </select>
        </label>
        <label>
          Snapshot walk-forward
          <select
            value={draftControls.snapshot}
            onChange={(e) => setDraftControls((prev) => ({ ...prev, snapshot: e.target.value }))}
          >
            <option value="latest">Najnowszy</option>
            {snapshots.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <label>
          Rola
          <select
            value={draftControls.role}
            onChange={(e) => setDraftControls((prev) => ({ ...prev, role: e.target.value }))}
          >
            {roles.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        </label>
        <label>
          Min. gier
          <input
            type="number"
            min={0}
            max={1000}
            value={draftControls.minGames}
            onChange={(e) => setDraftControls((prev) => ({
              ...prev,
              minGames: Math.max(0, Number(e.target.value) || 0),
            }))}
          />
        </label>
        <button className="ce-apply" type="button" onClick={applyControls} disabled={loading || (!controlsDirty && !error)}>
          {loading ? 'Liczenie…' : controlsDirty ? 'Przelicz' : error ? 'Spróbuj ponownie' : 'Aktualne'}
        </button>
        <label className="ce-search">
          Szukaj championa
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="np. Ahri, Zeri, 103…" />
        </label>
      </section>

      {error && <div className="ce-state error">{error}</div>}
      {loading && <div className="ce-state">Liczenie projekcji {appliedControls.method.toUpperCase()}…</div>}
      {data?.metadata.projection_warning && !error && (
        <div className="ce-state">{data.metadata.projection_warning}</div>
      )}

      {data && !loading && !error && (
        <>
          <section className="ce-stats">
            <Stat label="Punktów" value={`${visiblePoints.length}/${data.metadata.total_points}`} hint="po filtrze wyszukiwania" />
            <Stat label="Embedding dim" value={`${data.metadata.embedding_dim ?? '—'}`} hint={data.metadata.model_version} />
            <Stat label="Źródło" value={`${data.metadata.source_rows ?? '—'}`} hint="player-game rows" />
            <Stat label="Snapshot" value={data.metadata.snapshot || '—'} hint={data.metadata.reference_date?.slice(0, 10) || 'reference date'} />
          </section>

          <section className="ce-layout">
            <div className="ce-chart-card">
              <div className="ce-chart-head">
                <div>
                  <h2>{data.metadata.method.toUpperCase()} champion-role space</h2>
                  <p>Walk-forward: tylko historia przed snapshotem. Kolor = rola, rozmiar = liczba gier; kliknij punkt, żeby przypiąć szczegóły.</p>
                </div>
                <div className="ce-legend">
                  {Object.entries(ROLE_COLORS).map(([r, color]) => (
                    <span key={r}><i style={{ background: color }} />{r} <b>{roleCounts[r] || 0}</b></span>
                  ))}
                </div>
              </div>
              <svg className="ce-scatter" viewBox="0 0 1000 680" role="img" aria-label="Champion embedding scatter plot">
                <rect x="0" y="0" width="1000" height="680" rx="18" />
                <line x1="40" y1="340" x2="960" y2="340" />
                <line x1="500" y1="40" x2="500" y2="640" />
                {visiblePoints.map((p) => {
                  const x = 50 + p.x_norm * 900
                  const y = 630 - p.y_norm * 580
                  const isActive = activePoint?.champion_id === p.champion_id && activePoint?.role === p.role
                  return (
                    <g key={`${p.champion_id}-${p.role}`}>
                      <circle
                        cx={x}
                        cy={y}
                        r={pointRadius(p)}
                        fill={ROLE_COLORS[p.role || ''] || '#94a3b8'}
                        className={isActive ? 'active' : ''}
                        onMouseEnter={() => setHovered(p)}
                        onMouseLeave={() => setHovered(null)}
                        onClick={() => setSelected(p)}
                      />
                      {isActive && <text x={x + 10} y={y - 10}>{p.champion_name} · {p.role}</text>}
                    </g>
                  )
                })}
              </svg>
            </div>

            <aside className="ce-side">
              {activePoint ? <Tooltip point={activePoint} /> : (
                <div className="ce-empty-detail">
                  <h3>Wybierz punkt</h3>
                  <p>Najedź lub kliknij championa, żeby sprawdzić rolę, win rate, KDA, KP i poziom shrinkage.</p>
                </div>
              )}

              <div className="ce-table-card">
                <h3>Największa próbka</h3>
                <div className="ce-mini-table">
                  {[...visiblePoints]
                    .sort((a, b) => (b.n_games ?? 0) - (a.n_games ?? 0))
                    .slice(0, 12)
                    .map((p) => (
                      <button key={`${p.champion_id}-${p.role}`} onClick={() => setSelected(p)}>
                        <span>{p.champion_name}</span>
                        <small>{p.role} · {num(p.n_games, 0)} gier</small>
                      </button>
                    ))}
                </div>
              </div>
            </aside>
          </section>
        </>
      )}
    </div>
  )
}
