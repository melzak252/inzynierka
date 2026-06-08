import { useState, useEffect, useMemo } from 'react'
import { fetchMatchResults } from '../api/client'
import type { MatchResultItem } from '../types'
import './MatchResults.css'

const DAYS_OPTIONS = [7, 14, 30, 60, 90]
const BET_SIZE = 10

export default function MatchResults() {
  const [results, setResults] = useState<MatchResultItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [daysBack, setDaysBack] = useState(30)
  const [total, setTotal] = useState(0)
  const [showPositiveEvOnly, setShowPositiveEvOnly] = useState(false)
  const [selectedBookmaker, setSelectedBookmaker] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    setError(null)
    fetchMatchResults(daysBack)
      .then((data) => {
        setResults(data.results)
        setTotal(data.total)
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [daysBack])

  // Extract unique bookmakers from results
  const availableBookmakers = useMemo(() => {
    const bookmakers = new Set<string>()
    for (const r of results) {
      for (const b of r.bookmakers_with_ev) {
        bookmakers.add(b)
      }
    }
    return Array.from(bookmakers).sort()
  }, [results])

  // Filter results
  const filteredResults = useMemo(() => {
    return results.filter((r) => {
      if (showPositiveEvOnly && (r.best_ev_a ?? 0) <= 0 && (r.best_ev_b ?? 0) <= 0) {
        return false
      }
      if (selectedBookmaker && !r.bookmakers_with_ev.includes(selectedBookmaker)) {
        return false
      }
      return true
    })
  }, [results, showPositiveEvOnly, selectedBookmaker])

  const positiveEvCount = useMemo(() => {
    return results.filter((r) => (r.best_ev_a ?? 0) > 0 || (r.best_ev_b ?? 0) > 0).length
  }, [results])

  // Calculate P&L for +EV bets ($10 per bet)
  const pnlData = useMemo(() => {
    let totalPnl = 0
    let wins = 0
    let losses = 0
    let totalBets = 0

    for (const r of results) {
      const evA = r.best_ev_a ?? 0
      const evB = r.best_ev_b ?? 0

      // Side A had +EV
      if (evA > 0 && r.best_odds_a !== null) {
        totalBets++
        if (r.winner_side === 'team_a') {
          // Won: profit = $10 * (odds - 1)
          totalPnl += BET_SIZE * (r.best_odds_a - 1)
          wins++
        } else {
          // Lost: -$10
          totalPnl -= BET_SIZE
          losses++
        }
      }

      // Side B had +EV
      if (evB > 0 && r.best_odds_b !== null) {
        totalBets++
        if (r.winner_side === 'team_b') {
          totalPnl += BET_SIZE * (r.best_odds_b - 1)
          wins++
        } else {
          totalPnl -= BET_SIZE
          losses++
        }
      }
    }

    return { totalPnl, wins, losses, totalBets }
  }, [results])

  // Determine EV outcome for a match: 'won' | 'lost' | null
  const getEvOutcome = (r: MatchResultItem): 'won' | 'lost' | null => {
    const evA = r.best_ev_a ?? 0
    const evB = r.best_ev_b ?? 0
    if (evA <= 0 && evB <= 0) return null

    // Check if any +EV side won
    if (evA > 0 && r.winner_side === 'team_a') return 'won'
    if (evB > 0 && r.winner_side === 'team_b') return 'won'

    // If we had +EV but the +EV side didn't win
    return 'lost'
  }

  // Group results by date
  const groupedResults = useMemo(() => {
    const groups: { date: string; label: string; results: MatchResultItem[] }[] = []
    const seen = new Map<string, MatchResultItem[]>()

    for (const r of filteredResults) {
      const d = r.start_time_normalized ? new Date(r.start_time_normalized) : null
      const key = d
        ? `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
        : 'unknown'

      if (!seen.has(key)) {
        seen.set(key, [])
      }
      seen.get(key)!.push(r)
    }

    for (const [key, items] of seen) {
      const d = key === 'unknown' ? null : new Date(key + 'T12:00:00')
      const label = d
        ? d.toLocaleDateString('pl-PL', {
            weekday: 'long',
            day: 'numeric',
            month: 'long',
          })
        : 'Nieznana data'
      groups.push({ date: key, label: label.charAt(0).toUpperCase() + label.slice(1), results: items })
    }

    return groups
  }, [filteredResults])

  const formatTime = (dateStr: string | null) => {
    if (!dateStr) return '—'
    const d = new Date(dateStr)
    return d.toLocaleTimeString('pl-PL', {
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  const getWinnerClass = (side: string | null, teamSide: 'a' | 'b') => {
    if (!side) return ''
    if (side === 'team_a' && teamSide === 'a') return 'winner'
    if (side === 'team_b' && teamSide === 'b') return 'winner'
    return 'loser'
  }

  const hasPositiveEv = (r: MatchResultItem) => {
    return (r.best_ev_a ?? 0) > 0 || (r.best_ev_b ?? 0) > 0
  }

  const formatEv = (ev: number | null) => {
    if (ev === null || ev === undefined) return null
    const pct = (ev * 100).toFixed(1)
    return ev > 0 ? `+${pct}%` : `${pct}%`
  }

  const formatPnl = (amount: number) => {
    const sign = amount >= 0 ? '+' : ''
    return `${sign}$${amount.toFixed(2)}`
  }

  return (
    <div className="match-results-page">
      <div className="results-header">
        <div className="results-title-row">
          <div className="results-title">
            <h1>Wyniki meczów</h1>
            <span className="results-count">
              {filteredResults.length} {filteredResults.length === 1 ? 'mecz' : filteredResults.length < 5 ? 'mecze' : 'meczów'}
              {total !== filteredResults.length && ` z ${total}`}
            </span>
          </div>
          <button
            className={`ev-filter-btn${showPositiveEvOnly ? ' active' : ''}`}
            onClick={() => setShowPositiveEvOnly(!showPositiveEvOnly)}
            title="Pokaż tylko mecze z +EV"
          >
            <span className="ev-filter-icon">⚡</span> +EV
            {showPositiveEvOnly && positiveEvCount > 0 && (
              <span className="ev-filter-count">{positiveEvCount}</span>
            )}
          </button>
        </div>

        {/* P&L Summary Bar */}
        {pnlData.totalBets > 0 && (
          <div className={`pnl-bar ${pnlData.totalPnl >= 0 ? 'pnl-positive' : 'pnl-negative'}`}>
            <div className="pnl-label">P&L ($10/bet)</div>
            <div className="pnl-amount">{formatPnl(pnlData.totalPnl)}</div>
            <div className="pnl-details">
              <span className="pnl-wins">✓ {pnlData.wins}</span>
              <span className="pnl-losses">✗ {pnlData.losses}</span>
              <span className="pnl-bets">{pnlData.totalBets} zakładów</span>
            </div>
          </div>
        )}

        <div className="results-controls">
          <span className="controls-label">Okres:</span>
          <div className="days-pills">
            {DAYS_OPTIONS.map((d) => (
              <button
                key={d}
                className={`days-pill${daysBack === d ? ' active' : ''}`}
                onClick={() => setDaysBack(d)}
              >
                {d}d
              </button>
            ))}
          </div>
          {availableBookmakers.length > 0 && (
            <div className="bookmaker-filter">
              <span className="controls-label">Bukmacher:</span>
              <div className="bookmaker-pills">
                <button
                  className={`bookmaker-pill${!selectedBookmaker ? ' active' : ''}`}
                  onClick={() => setSelectedBookmaker(null)}
                >
                  Wszyscy
                </button>
                {availableBookmakers.map((b) => (
                  <button
                    key={b}
                    className={`bookmaker-pill${selectedBookmaker === b ? ' active' : ''}`}
                    onClick={() => setSelectedBookmaker(selectedBookmaker === b ? null : b)}
                  >
                    {b}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {loading && <div className="results-loading">Ładowanie wyników...</div>}
      {error && <div className="results-error">Błąd: {error}</div>}

      {!loading && !error && filteredResults.length === 0 && (
        <div className="results-empty">
          {showPositiveEvOnly || selectedBookmaker
            ? 'Brak wyników pasujących do filtrów.'
            : 'Brak wyników w wybranym okresie.'}
        </div>
      )}

      {!loading && !error && groupedResults.map((group) => (
        <div key={group.date} className="results-date-group">
          <div className="date-group-header">{group.label}</div>
          <div className="results-grid">
            {group.results.map((r) => {
              const teamAClass = getWinnerClass(r.winner_side, 'a')
              const teamBClass = getWinnerClass(r.winner_side, 'b')
              const hasResult = r.team_a_score !== null && r.team_b_score !== null
              const isPositiveEv = hasPositiveEv(r)
              const evOutcome = getEvOutcome(r)

              // Determine card class based on EV outcome
              let cardEvClass = ''
              if (evOutcome === 'won') cardEvClass = ' ev-won'
              else if (evOutcome === 'lost') cardEvClass = ' ev-lost'

              return (
                <div key={r.canonical_match_id} className={`result-card${cardEvClass}`}>
                  <div className="result-card-header">
                    <span className="result-league">{r.league || 'Nieznana liga'}</span>
                    {r.best_of && (
                      <span className={`result-bo-badge bo${r.best_of}`}>
                        Bo{r.best_of}
                      </span>
                    )}
                    {isPositiveEv && (
                      <span className={`result-ev-indicator${evOutcome === 'won' ? ' ev-won' : evOutcome === 'lost' ? ' ev-lost' : ''}`}>
                        {evOutcome === 'won' ? '✓' : evOutcome === 'lost' ? '✗' : '⚡'} +EV
                      </span>
                    )}
                    <span className="result-time">{formatTime(r.start_time_normalized)}</span>
                  </div>

                  <div className="result-card-body">
                    <div className={`result-team ${teamAClass}`}>
                      <span className="result-team-name">{r.team_a_name || '?'}</span>
                      {hasResult && (
                        <span className={`result-score ${teamAClass}`}>
                          {r.team_a_score}
                        </span>
                      )}
                    </div>
                    <div className="result-vs-divider">
                      <span className="result-vs">vs</span>
                    </div>
                    <div className={`result-team ${teamBClass}`}>
                      <span className="result-team-name">{r.team_b_name || '?'}</span>
                      {hasResult && (
                        <span className={`result-score ${teamBClass}`}>
                          {r.team_b_score}
                        </span>
                      )}
                    </div>
                  </div>

                  {/* EV signals row */}
                  {isPositiveEv && (
                    <div className="result-ev-row">
                      {(r.best_ev_a ?? 0) > 0 && (
                        <span className={`result-ev-badge ev-a${r.winner_side === 'team_a' ? ' ev-bet-won' : ' ev-bet-lost'}`}>
                          {r.team_a_name?.split(' ').slice(-1)[0]}: {formatEv(r.best_ev_a)}
                          {r.best_odds_a !== null && <span className="ev-odds">@{r.best_odds_a.toFixed(2)}</span>}
                        </span>
                      )}
                      {(r.best_ev_b ?? 0) > 0 && (
                        <span className={`result-ev-badge ev-b${r.winner_side === 'team_b' ? ' ev-bet-won' : ' ev-bet-lost'}`}>
                          {r.team_b_name?.split(' ').slice(-1)[0]}: {formatEv(r.best_ev_b)}
                          {r.best_odds_b !== null && <span className="ev-odds">@{r.best_odds_b.toFixed(2)}</span>}
                        </span>
                      )}
                      {r.bookmakers_with_ev.length > 0 && (
                        <span className="result-ev-bookmakers">
                          {r.bookmakers_with_ev.join(', ')}
                        </span>
                      )}
                    </div>
                  )}

                  <div className="result-card-footer">
                    {r.result_source && (
                      <span className="result-source-badge">{r.result_source}</span>
                    )}
                    {hasResult && r.winner_name && (
                      <span className="result-winner-label">
                        🏆 {r.winner_name}
                      </span>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}
