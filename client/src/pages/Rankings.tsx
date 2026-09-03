import { FormEvent, useEffect, useMemo, useState } from 'react'
import { fetchRankings } from '../api/client'
import type { RankingEntityType, RankingsResponse, RatingSystem } from '../types'
import './Rankings.css'

const RATING_SYSTEMS: Array<{ id: RatingSystem; label: string; detail: string }> = [
  { id: 'unified', label: 'Unified', detail: 'średnia pozycji percentylowych' },
  { id: 'elo', label: 'Elo', detail: 'klasyczny rating wyniku' },
  { id: 'gl', label: 'Glicko-2', detail: 'rating z niepewnością RD' },
  { id: 'ts', label: 'TrueSkill', detail: 'rating probabilistyczny' },
  { id: 'os', label: 'OpenSkill', detail: 'rating probabilistyczny' },
  { id: 'pl', label: 'Plackett–Luce', detail: 'model rankingowy' },
  { id: 'tm', label: 'Thurstone–Mosteller', detail: 'model rankingowy' },
]

function formatRating(value: number, system: RatingSystem): string {
  return value.toLocaleString('pl-PL', {
    minimumFractionDigits: system === 'unified' ? 1 : system === 'elo' || system === 'gl' ? 1 : 2,
    maximumFractionDigits: system === 'unified' ? 1 : system === 'elo' || system === 'gl' ? 1 : 2,
  })
}

function formatDate(value: string | null): string {
  if (!value) return '—'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return new Intl.DateTimeFormat('pl-PL', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(parsed)
}

function uncertainty(row: RankingsResponse['rankings'][number]): string {
  if (row.rating_system === 'unified') return `${row.system_count} syst.`
  if (row.rd != null) return `RD ${row.rd.toFixed(1)}`
  if (row.sigma != null) return `σ ${row.sigma.toFixed(2)}`
  return '—'
}

export default function Rankings() {
  const [entityType, setEntityType] = useState<RankingEntityType>('team')
  const [ratingSystem, setRatingSystem] = useState<RatingSystem>('unified')
  const [minGames, setMinGames] = useState(10)
  const [query, setQuery] = useState('')
  const [appliedQuery, setAppliedQuery] = useState('')
  const [data, setData] = useState<RankingsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [reloadToken, setReloadToken] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    let cancelled = false

    setLoading(true)
    setError(null)
    fetchRankings({
      entityType,
      ratingSystem,
      search: appliedQuery,
      minGames,
      limit: 100,
      signal: controller.signal,
    })
      .then(result => {
        if (!cancelled) setData(result)
      })
      .catch(reason => {
        if (reason instanceof DOMException && reason.name === 'AbortError') return
        if (!cancelled) setError(reason instanceof Error ? reason.message : 'Nie udało się pobrać rankingu')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
      controller.abort()
    }
  }, [entityType, ratingSystem, minGames, appliedQuery, reloadToken])

  const system = RATING_SYSTEMS.find(item => item.id === ratingSystem) ?? RATING_SYSTEMS[0]
  const leader = data?.rankings[0]
  const availableLabels = useMemo(
    () => (data?.available_rating_systems ?? [])
      .map(id => RATING_SYSTEMS.find(systemItem => systemItem.id === id)?.label ?? id)
      .join(', '),
    [data],
  )

  const submitSearch = (event: FormEvent) => {
    event.preventDefault()
    setAppliedQuery(query.trim())
  }

  const switchEntity = (next: RankingEntityType) => {
    setEntityType(next)
    setQuery('')
    setAppliedQuery('')
  }

  return (
    <div className="rankings-page">
      <header className="rankings-hero">
        <div>
          <span className="rankings-eyebrow">AKTUALNY SNAPSHOT SIŁY</span>
          <h1>Rankingi drużyn i zawodników</h1>
          <p>Domyślny ranking Unified łączy pozycje percentylowe ze wszystkich kompletnych systemów. Możesz też sprawdzić każdy rating osobno; ich surowe skale nie są bezpośrednio porównywalne.</p>
        </div>
        <div className="rankings-snapshot">
          <span>Wersja ratingów</span>
          <strong>{data?.ratings_version ?? 'brak'}</strong>
          <small>cutoff {formatDate(data?.data_cutoff_at ?? null)}</small>
        </div>
      </header>

      <section className="rankings-controls" aria-label="Filtry rankingu">
        <div className="rankings-entity-tabs" role="tablist" aria-label="Typ rankingu">
          <button type="button" role="tab" aria-selected={entityType === 'team'} className={entityType === 'team' ? 'active' : ''} onClick={() => switchEntity('team')}>Drużyny</button>
          <button type="button" role="tab" aria-selected={entityType === 'player'} className={entityType === 'player' ? 'active' : ''} onClick={() => switchEntity('player')}>Zawodnicy</button>
        </div>

        <div className="rankings-system-list" aria-label="System ratingowy">
          {RATING_SYSTEMS.map(item => (
            <button
              type="button"
              key={item.id}
              className={ratingSystem === item.id ? 'active' : ''}
              onClick={() => setRatingSystem(item.id)}
              title={item.detail}
            >
              {item.label}
            </button>
          ))}
        </div>

        <form className="rankings-filter-row" onSubmit={submitSearch}>
          <label>
            <span>Szukaj</span>
            <input value={query} onChange={event => setQuery(event.target.value)} placeholder={entityType === 'team' ? 'Nazwa drużyny' : 'Nick zawodnika'} maxLength={100} />
          </label>
          <label>
            <span>Minimum gier</span>
            <select value={minGames} onChange={event => setMinGames(Number(event.target.value))}>
              {[1, 5, 10, 20, 50, 100].map(value => <option value={value} key={value}>{value}</option>)}
            </select>
          </label>
          <button type="submit" className="rankings-search">Zastosuj</button>
        </form>
      </section>

      {error && (
        <div className="rankings-message error" role="alert">
          <div><strong>Nie udało się pobrać rankingu.</strong><span>{error}</span></div>
          <button type="button" onClick={() => setReloadToken(value => value + 1)}>Spróbuj ponownie</button>
        </div>
      )}

      {loading && !data && <div className="rankings-message">Pobieram najnowszy snapshot ratingów…</div>}

      {data && (
        <>
          <section className="rankings-summary" aria-label="Podsumowanie rankingu">
            <article className="leader-card">
              <span>Lider · {system.label}</span>
              <strong>{leader?.entity_name ?? 'Brak danych'}</strong>
              <small>{leader ? `${formatRating(leader.rating_value, ratingSystem)} · ${leader.games_played} gier` : 'Zmień filtr lub system ratingowy'}</small>
            </article>
            <article>
              <span>Zakwalifikowani</span>
              <strong>{data.total.toLocaleString('pl-PL')}</strong>
              <small>minimum {minGames} gier</small>
            </article>
            <article>
              <span>System</span>
              <strong>{system.label}</strong>
              <small>{system.detail}</small>
            </article>
            <article>
              <span>Snapshot</span>
              <strong>{formatDate(data.snapshot_at)}</strong>
              <small>dane do {formatDate(data.data_cutoff_at)}</small>
            </article>
          </section>

          <section className="rankings-board">
            <div className="rankings-board-heading">
              <div>
                <span>{entityType === 'team' ? 'TEAM LEADERBOARD' : 'PLAYER LEADERBOARD'}</span>
                <h2>{entityType === 'team' ? 'Najsilniejsze drużyny' : 'Najwyżej oceniani zawodnicy'}</h2>
              </div>
              <p>{ratingSystem === 'unified' ? `Pokazano ${data.rankings.length} z ${data.total}. Wynik 0–100 to średnia pozycji percentylowych; wymagane są wszystkie dostępne systemy.` : `Pokazano ${data.rankings.length} z ${data.total}. Ranking według surowej wartości ${system.label}; niepewność jest raportowana osobno.`}</p>
            </div>

            {loading && <div className="rankings-progress" aria-label="Odświeżanie rankingu"><span /></div>}

            <div className="rankings-table-wrap">
              <table className="rankings-table">
                <thead>
                  <tr>
                    <th>Pozycja</th>
                    <th>{entityType === 'team' ? 'Drużyna' : 'Zawodnik'}</th>
                    {entityType === 'player' && <th>Drużyna / rola</th>}
                    <th>Rating</th>
                    <th>Niepewność</th>
                    <th>Gry</th>
                    <th>Ostatni mecz</th>
                  </tr>
                </thead>
                <tbody>
                  {data.rankings.map(row => (
                    <tr key={`${row.normalized_entity_name}-${row.rating_system}`}>
                      <td><span className={`rank-badge rank-${row.rank <= 3 ? row.rank : 'other'}`}>{row.rank}</span></td>
                      <td><strong>{row.entity_name}</strong>{entityType === 'team' && <small>{row.normalized_entity_name}</small>}</td>
                      {entityType === 'player' && <td><strong className="team-label">{row.team_name || '—'}</strong><small>{row.role || 'rola nieznana'}</small></td>}
                      <td><strong className="rating-value">{formatRating(row.rating_value, ratingSystem)}</strong></td>
                      <td>{uncertainty(row)}</td>
                      <td>{row.games_played}</td>
                      <td>{formatDate(row.last_match_at)}</td>
                    </tr>
                  ))}
                  {!data.rankings.length && (
                    <tr>
                      <td colSpan={entityType === 'player' ? 7 : 6} className="rankings-empty">
                        <strong>{data.ratings_version ? 'Brak pozycji dla tych filtrów.' : 'Brak zakończonego przebiegu ratingów.'}</strong>
                        <span>{data.ratings_version ? `Dostępne systemy: ${availableLabels || 'brak'}. Zmniejsz minimum gier lub wyczyść wyszukiwanie.` : 'Uruchom zakończony rebuild ratingów, aby utworzyć ranking.'}</span>
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>

          <p className="rankings-footnote">Unified nie uśrednia surowych ratingów: najpierw zamienia pozycję w każdym systemie na percentyl 0–100, a potem liczy średnią wyłącznie dla encji z kompletem systemów. Ranking jest bieżącym snapshotem do predykcji nadchodzących meczów, nie historycznym ratingiem na dowolną datę.</p>
        </>
      )}
    </div>
  )
}
