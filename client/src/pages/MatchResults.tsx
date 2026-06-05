import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { fetchMatchResults } from '../api/client'
import type { MatchResultItem } from '../types'
import './MatchResults.css'

const DAYS_OPTIONS = [7, 14, 30, 60, 90]

export default function MatchResults() {
  const [results, setResults] = useState<MatchResultItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [daysBack, setDaysBack] = useState(30)
  const [total, setTotal] = useState(0)

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

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return '—'
    const d = new Date(dateStr)
    return d.toLocaleDateString('pl-PL', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  const formatScore = (score: number | null) => {
    return score !== null ? score : '—'
  }

  const getWinnerClass = (side: string | null, teamSide: 'a' | 'b') => {
    if (!side) return ''
    if (side === 'team_a' && teamSide === 'a') return 'winner'
    if (side === 'team_b' && teamSide === 'b') return 'winner'
    return 'loser'
  }

  return (
    <div className="match-results-page">
      <div className="results-header">
        <h1>Wyniki meczów</h1>
        <div className="results-controls">
          <label>Ostatnie:</label>
          <select
            value={daysBack}
            onChange={(e) => setDaysBack(Number(e.target.value))}
            className="days-select"
          >
            {DAYS_OPTIONS.map((d) => (
              <option key={d} value={d}>
                {d} dni
              </option>
            ))}
          </select>
          <span className="results-count">
            {total} {total === 1 ? 'mecz' : total < 5 ? 'mecze' : 'meczów'}
          </span>
        </div>
      </div>

      {loading && <div className="results-loading">Ładowanie wyników...</div>}
      {error && <div className="results-error">Błąd: {error}</div>}

      {!loading && !error && results.length === 0 && (
        <div className="results-empty">Brak wyników w wybranym okresie.</div>
      )}

      {!loading && !error && results.length > 0 && (
        <div className="results-table-wrapper">
          <table className="results-table">
            <thead>
              <tr>
                <th>Data</th>
                <th>Liga</th>
                <th>Bo</th>
                <th className="team-col">Team A</th>
                <th className="score-col">Wynik</th>
                <th className="team-col">Team B</th>
                <th>Źródło</th>
              </tr>
            </thead>
            <tbody>
              {results.map((r) => (
                <tr key={r.canonical_match_id}>
                  <td className="date-cell">{formatDate(r.start_time_normalized)}</td>
                  <td className="league-cell">{r.league || '—'}</td>
                  <td className="bo-cell">
                    {r.best_of ? `Bo${r.best_of}` : '—'}
                  </td>
                  <td className={`team-cell ${getWinnerClass(r.winner_side, 'a')}`}>
                    {r.team_a_name || '—'}
                  </td>
                  <td className="score-cell">
                    <span className={`score-a ${getWinnerClass(r.winner_side, 'a')}`}>
                      {formatScore(r.team_a_score)}
                    </span>
                    {' : '}
                    <span className={`score-b ${getWinnerClass(r.winner_side, 'b')}`}>
                      {formatScore(r.team_b_score)}
                    </span>
                  </td>
                  <td className={`team-cell ${getWinnerClass(r.winner_side, 'b')}`}>
                    {r.team_b_name || '—'}
                  </td>
                  <td className="source-cell">
                    {r.result_source ? (
                      <span className="source-badge">{r.result_source}</span>
                    ) : (
                      '—'
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
