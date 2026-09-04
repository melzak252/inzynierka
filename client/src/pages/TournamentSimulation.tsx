import { useState, useEffect } from 'react';
import { fetchTournaments, fetchTournamentBracket, simulateTournament } from '../api/client';
import type { TournamentSummary, TournamentSimulationResponse, BracketMatch } from '../types';
import './TournamentSimulation.css';

export default function TournamentSimulation() {
  const [tournaments, setTournaments] = useState<TournamentSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string>('lck_2026_playoffs');
  const [data, setData] = useState<TournamentSimulationResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [simulating, setSimulating] = useState<boolean>(false);
  const [simCount, setSimCount] = useState<number>(10000);
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchTournaments()
      .then((list) => {
        setTournaments(list);
        if (list.length > 0 && !selectedId) {
          setSelectedId(list[0].id);
        }
      })
      .catch((err) => setError(err instanceof Error ? err.message : 'Błąd ładowania turniejów'));
  }, [selectedId]);

  useEffect(() => {
    if (!selectedId) return;
    setLoading(true);
    fetchTournamentBracket(selectedId)
      .then((res) => {
        setData(res);
        setOverrides({});
        setLoading(false);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Błąd ładowania drabinki');
        setLoading(false);
      });
  }, [selectedId]);

  const handleSimulate = async () => {
    if (!selectedId) return;
    setSimulating(true);
    try {
      const res = await simulateTournament(selectedId, simCount, overrides);
      setData(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Błąd symulacji');
    } finally {
      setSimulating(false);
    }
  };

  const handleToggleWinner = (matchId: string, team: string | null) => {
    if (!team) return;
    setOverrides((prev) => {
      const updated = { ...prev };
      if (updated[matchId] === team) {
        delete updated[matchId];
      } else {
        updated[matchId] = team;
      }
      return updated;
    });
  };

  const handleResetOverrides = () => {
    setOverrides({});
  };

  if (loading) {
    return <div className="tournament-container"><div className="loading-state">Ładowanie drabinki i symulatora...</div></div>;
  }

  const bracket = data?.bracket || {};
  const upperMatches = Object.values(bracket).filter((m) => m.bracket_section === 'upper');
  const lowerMatches = Object.values(bracket).filter((m) => m.bracket_section === 'lower');
  const finalMatches = Object.values(bracket).filter((m) => m.bracket_section === 'final');

  const renderMatchCard = (m: BracketMatch) => {
    const isCompleted = m.winner !== null;
    const manualWinner = overrides[m.id];
    const effectiveWinner = manualWinner || m.winner;

    return (
      <div key={m.id} className={`bracket-match-card ${isCompleted ? 'completed' : ''} ${manualWinner ? 'overridden' : ''}`}>
        <div className="match-card-header">
          <span className="round-badge">{m.round_name}</span>
          <span className="bo-badge">Bo{m.best_of}</span>
        </div>
        <div className="match-card-teams">
          <div
            className={`team-row ${effectiveWinner === m.team1 ? 'winner' : ''} ${m.team1 ? 'clickable' : ''}`}
            onClick={() => handleToggleWinner(m.id, m.team1)}
            title={m.team1 ? `Kliknij, aby wymusić wygraną ${m.team1}` : ''}
          >
            <span className="team-name">{m.team1 || 'TBD'}</span>
            {m.score1 !== null && <span className="team-score">{m.score1}</span>}
            {effectiveWinner === m.team1 && <span className="crown-icon">👑</span>}
          </div>
          <div
            className={`team-row ${effectiveWinner === m.team2 ? 'winner' : ''} ${m.team2 ? 'clickable' : ''}`}
            onClick={() => handleToggleWinner(m.id, m.team2)}
            title={m.team2 ? `Kliknij, aby wymusić wygraną ${m.team2}` : ''}
          >
            <span className="team-name">{m.team2 || 'TBD'}</span>
            {m.score2 !== null && <span className="team-score">{m.score2}</span>}
            {effectiveWinner === m.team2 && <span className="crown-icon">👑</span>}
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className="tournament-container">
      <header className="tournament-header">
        <div>
          <h1>🏆 Symulacja Drabinki Turniejowej</h1>
          <p className="subtitle">
            Pobieraj rzeczywisty stan drabinki i symuluj pozostałe mecze metodą Monte Carlo na modelu operacyjnym.
          </p>
        </div>
        <div className="tournament-controls">
          <select
            value={selectedId}
            onChange={(e) => setSelectedId(e.target.value)}
            className="tournament-select"
          >
            {tournaments.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name} ({t.region})
              </option>
            ))}
          </select>
          <div className="sim-config">
            <label>Próby:</label>
            <select
              value={simCount}
              onChange={(e) => setSimCount(Number(e.target.value))}
              className="sim-count-select"
            >
              <option value={1000}>1 000</option>
              <option value={5000}>5 000</option>
              <option value={10000}>10 000</option>
              <option value={25000}>25 000</option>
            </select>
          </div>
          <button
            className="simulate-btn"
            onClick={handleSimulate}
            disabled={simulating}
          >
            {simulating ? '⏳ Symulowanie...' : '⚡ Uruchom symulację'}
          </button>
          {Object.keys(overrides).length > 0 && (
            <button className="reset-btn" onClick={handleResetOverrides}>
              Reset scenariuszy ({Object.keys(overrides).length})
            </button>
          )}
        </div>
      </header>

      {error && <div className="error-banner">{error}</div>}

      <div className="simulation-layout">
        <section className="standings-panel">
          <h2>📊 Szanse na końcowy wynik ({data?.simulations.toLocaleString()} symulacji)</h2>
          <table className="standings-table">
            <thead>
              <tr>
                <th>Drużyna</th>
                <th>🥇 Mistrz</th>
                <th>🥈 Top 2</th>
                <th>🥉 Top 3</th>
                <th>Top 4</th>
              </tr>
            </thead>
            <tbody>
              {data?.standings.map((s) => (
                <tr key={s.team}>
                  <td className="team-cell"><strong>{s.team}</strong></td>
                  <td className="prob-cell champ-prob">{(s.champion_prob * 100).toFixed(1)}%</td>
                  <td className="prob-cell">{(s.top2_prob * 100).toFixed(1)}%</td>
                  <td className="prob-cell">{(s.top3_prob * 100).toFixed(1)}%</td>
                  <td className="prob-cell">{(s.top4_prob * 100).toFixed(1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="scenario-tip">
            💡 <strong>Tryb scenariuszy (What-if):</strong> Kliknij na dowolną drużynę w drabince, aby wymusić jej zwycięstwo i przeliczyć resztę turnieju.
          </p>
        </section>

        <section className="bracket-panel">
          <h2>Drabinka Playoffów (Double Elimination)</h2>

          <div className="bracket-grid">
            <div className="bracket-column">
              <h3>Upper Bracket</h3>
              <div className="matches-list">
                {upperMatches.map(renderMatchCard)}
              </div>
            </div>

            <div className="bracket-column">
              <h3>Lower Bracket</h3>
              <div className="matches-list">
                {lowerMatches.map(renderMatchCard)}
              </div>
            </div>

            <div className="bracket-column">
              <h3>Wielki Finał</h3>
              <div className="matches-list">
                {finalMatches.map(renderMatchCard)}
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
