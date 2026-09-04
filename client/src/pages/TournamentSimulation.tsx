import { useState, useEffect } from 'react';
import {
  fetchTournaments,
  fetchTournamentBracket,
  simulateTournament,
  fetchWorldsDefaultTeams,
  simulateWorlds,
} from '../api/client';
import type {
  TournamentSummary,
  TournamentSimulationResponse,
  BracketMatch,
  WorldsSimulationResponse,
} from '../types';
import './TournamentSimulation.css';

export default function TournamentSimulation() {
  const [activeTab, setActiveTab] = useState<'regional' | 'worlds'>('regional');

  // Regional state
  const [tournaments, setTournaments] = useState<TournamentSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string>('lck_2026_playoffs');
  const [data, setData] = useState<TournamentSimulationResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [simulating, setSimulating] = useState<boolean>(false);
  const [simCount, setSimCount] = useState<number>(10000);
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  // Worlds state
  const [worldsTeams, setWorldsTeams] = useState<string[]>([]);
  const [worldsData, setWorldsData] = useState<WorldsSimulationResponse | null>(null);
  const [worldsSimulating, setWorldsSimulating] = useState<boolean>(false);
  const [newTeamInput, setNewTeamInput] = useState<string>('');

  useEffect(() => {
    fetchTournaments()
      .then((list) => {
        setTournaments(list);
        if (list.length > 0 && !selectedId) {
          setSelectedId(list[0].id);
        }
      })
      .catch((err) => setError(err instanceof Error ? err.message : 'Błąd ładowania turniejów'));

    fetchWorldsDefaultTeams()
      .then((res) => {
        setWorldsTeams(res.default_teams);
      })
      .catch((err) => console.error('Błąd ładowania drużyn Worlds:', err));
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

  const handleSimulateWorlds = async () => {
    setWorldsSimulating(true);
    try {
      const res = await simulateWorlds(worldsTeams, 5000);
      setWorldsData(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Błąd symulacji Worlds');
    } finally {
      setWorldsSimulating(false);
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

  const handleUpdateWorldsTeam = (index: number, val: string) => {
    setWorldsTeams((prev) => {
      const updated = [...prev];
      updated[index] = val;
      return updated;
    });
  };

  const handleAddWorldsTeam = () => {
    if (!newTeamInput.trim()) return;
    if (worldsTeams.length < 16) {
      setWorldsTeams((prev) => [...prev, newTeamInput.trim()]);
      setNewTeamInput('');
    }
  };

  const handleRemoveWorldsTeam = (index: number) => {
    setWorldsTeams((prev) => prev.filter((_, i) => i !== index));
  };

  if (loading && activeTab === 'regional') {
    return <div className="tournament-container"><div className="loading-state">Ładowanie drabinki i symulatora...</div></div>;
  }

  const bracket = data?.bracket || {};
  const allMatches = Object.values(bracket);

  // Group matches chronologically by progression stage
  const upperR1 = allMatches.filter((m) => m.bracket_section === 'upper' && m.round_name.includes('Round 1'));
  const upperR2 = allMatches.filter((m) => m.bracket_section === 'upper' && (m.round_name.includes('Round 2') || m.round_name.includes('Semifinal')));
  const upperFinal = allMatches.filter((m) => m.bracket_section === 'upper' && m.round_name.includes('Upper Final'));

  const lowerR1 = allMatches.filter((m) => m.bracket_section === 'lower' && m.round_name.includes('Lower Round 1'));
  const lowerR2 = allMatches.filter((m) => m.bracket_section === 'lower' && m.round_name.includes('Lower Round 2'));
  const lowerSemi = allMatches.filter((m) => m.bracket_section === 'lower' && (m.round_name.includes('Lower Round 3') || m.round_name.includes('Lower Semifinal')));
  const lowerFinal = allMatches.filter((m) => m.bracket_section === 'lower' && m.round_name.includes('Lower Final'));

  const grandFinal = allMatches.filter((m) => m.bracket_section === 'final');

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
          <h1>🏆 Symulacja Turniejów i Mistrzostw Świata</h1>
          <p className="subtitle">
            Pobieraj rzeczywisty stan drabinek ligowych lub symuluj pełne Mistrzostwa Świata (Worlds) z własną listą drużyn.
          </p>
        </div>

        <div className="tab-switcher">
          <button
            className={`tab-btn ${activeTab === 'regional' ? 'active' : ''}`}
            onClick={() => setActiveTab('regional')}
          >
            Drabinki Regionalne (LCK / LEC / LPL)
          </button>
          <button
            className={`tab-btn ${activeTab === 'worlds' ? 'active' : ''}`}
            onClick={() => setActiveTab('worlds')}
          >
            🌍 Worlds 2026 (Swiss + Knockout)
          </button>
        </div>

        {activeTab === 'regional' ? (
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
              <button className="reset-btn" onClick={() => setOverrides({})}>
                Reset scenariuszy ({Object.keys(overrides).length})
              </button>
            )}
          </div>
        ) : (
          <div className="tournament-controls">
            <button
              className="simulate-btn"
              onClick={handleSimulateWorlds}
              disabled={worldsSimulating || worldsTeams.length !== 16}
            >
              {worldsSimulating ? '⏳ Symulacja Worlds...' : '⚡ Symuluj Worlds (5 000 prób)'}
            </button>
          </div>
        )}
      </header>

      {error && <div className="error-banner">{error}</div>}

      {activeTab === 'regional' ? (
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
            <h2>Drzewo Turniejowe (Chronologiczny układ rund)</h2>

            <div className="bracket-section-group">
              <h3 className="section-heading">Upper Bracket</h3>
              <div className="bracket-stages-flow">
                {upperR1.length > 0 && (
                  <div className="stage-column">
                    <div className="stage-title">Runda 1 (Ćwierćfinały)</div>
                    <div className="stage-matches">{upperR1.map(renderMatchCard)}</div>
                  </div>
                )}
                {upperR2.length > 0 && (
                  <div className="stage-column">
                    <div className="stage-title">Półfinały Upper</div>
                    <div className="stage-matches">{upperR2.map(renderMatchCard)}</div>
                  </div>
                )}
                {upperFinal.length > 0 && (
                  <div className="stage-column">
                    <div className="stage-title">Finał Upper Bracket</div>
                    <div className="stage-matches">{upperFinal.map(renderMatchCard)}</div>
                  </div>
                )}
              </div>
            </div>

            <div className="bracket-section-group">
              <h3 className="section-heading">Lower Bracket</h3>
              <div className="bracket-stages-flow">
                {lowerR1.length > 0 && (
                  <div className="stage-column">
                    <div className="stage-title">Lower Runda 1</div>
                    <div className="stage-matches">{lowerR1.map(renderMatchCard)}</div>
                  </div>
                )}
                {lowerR2.length > 0 && (
                  <div className="stage-column">
                    <div className="stage-title">Lower Runda 2</div>
                    <div className="stage-matches">{lowerR2.map(renderMatchCard)}</div>
                  </div>
                )}
                {lowerSemi.length > 0 && (
                  <div className="stage-column">
                    <div className="stage-title">Półfinał Lower</div>
                    <div className="stage-matches">{lowerSemi.map(renderMatchCard)}</div>
                  </div>
                )}
                {lowerFinal.length > 0 && (
                  <div className="stage-column">
                    <div className="stage-title">Finał Lower Bracket</div>
                    <div className="stage-matches">{lowerFinal.map(renderMatchCard)}</div>
                  </div>
                )}
              </div>
            </div>

            <div className="bracket-section-group final-group">
              <h3 className="section-heading">Wielki Finał</h3>
              <div className="bracket-stages-flow">
                <div className="stage-column">
                  <div className="stage-title">Mecz o Mistrzostwo</div>
                  <div className="stage-matches">{grandFinal.map(renderMatchCard)}</div>
                </div>
              </div>
            </div>
          </section>
        </div>
      ) : (
        <div className="worlds-layout">
          <section className="worlds-teams-editor">
            <h2>Uczestnicy Worlds 2026 (16 drużyn w fazie Swiss)</h2>
            <p className="subtitle-sm">
              Możesz edytować nazwy drużyn lub wpisać własnych faworytów. Model użyje ich aktualnych ratingów.
            </p>

            <div className="teams-grid">
              {worldsTeams.map((team, idx) => (
                <div key={idx} className="team-input-card">
                  <span className="team-slot-num">#{idx + 1}</span>
                  <input
                    type="text"
                    value={team}
                    onChange={(e) => handleUpdateWorldsTeam(idx, e.target.value)}
                    className="team-text-input"
                  />
                  <button
                    className="remove-team-btn"
                    onClick={() => handleRemoveWorldsTeam(idx)}
                    title="Usuń slot"
                  >
                    ✕
                  </button>
                </div>
              ))}
            </div>

            {worldsTeams.length < 16 && (
              <div className="add-team-bar">
                <input
                  type="text"
                  placeholder="Wpisz nazwę drużyny..."
                  value={newTeamInput}
                  onChange={(e) => setNewTeamInput(e.target.value)}
                  className="add-team-input"
                />
                <button className="add-btn" onClick={handleAddWorldsTeam}>
                  + Dodaj drużynę ({worldsTeams.length}/16)
                </button>
              </div>
            )}
          </section>

          <section className="worlds-results-panel">
            <h2>🏆 Wyniki Symulacji Worlds 2026</h2>
            {worldsData ? (
              <table className="standings-table">
                <thead>
                  <tr>
                    <th>Drużyna</th>
                    <th>🥇 Puchar Worlds</th>
                    <th>🥈 Finał (Top 2)</th>
                    <th>Półfinał (Top 4)</th>
                    <th>Wyjście ze Swiss (Top 8)</th>
                  </tr>
                </thead>
                <tbody>
                  {worldsData.standings.map((s) => (
                    <tr key={s.team}>
                      <td className="team-cell"><strong>{s.team}</strong></td>
                      <td className="prob-cell champ-prob">{(s.champion_prob * 100).toFixed(1)}%</td>
                      <td className="prob-cell">{(s.top2_prob * 100).toFixed(1)}%</td>
                      <td className="prob-cell">{(s.top4_prob * 100).toFixed(1)}%</td>
                      <td className="prob-cell">{(s.top8_swiss_prob * 100).toFixed(1)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="empty-state">
                <p>Kliknij <strong>⚡ Symuluj Worlds</strong> powyżej, aby przeprowadzić 5 000 pełnych symulacji fazy Swiss (Bo1/Bo3) i fazy pucharowej (Bo5)!</p>
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
