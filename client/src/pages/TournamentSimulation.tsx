import { useEffect, useState } from 'react';
import {
  fetchTournaments,
  fetchTournamentBracket,
  simulateTournament,
  simulateWorlds,
} from '../api/client';
import type {
  BracketMatch,
  TournamentSimulationResponse,
  TournamentSummary,
  WorldsSimulationResponse,
  WorldsTeamInput,
} from '../types';
import './TournamentSimulation.css';

const INITIAL_DIRECT_TEAMS: WorldsTeamInput[] = [
  { team: '', region: 'LCK', pool: 1 }, { team: '', region: 'LPL', pool: 1 },
  { team: '', region: 'LCS', pool: 1 }, { team: '', region: 'LEC', pool: 1 },
  { team: '', region: 'LCP', pool: 2 }, { team: '', region: 'CBLOL', pool: 2 },
  { team: '', region: 'LCK', pool: 2 }, { team: '', region: 'LPL', pool: 2 },
  { team: '', region: 'LCS', pool: 3 }, { team: '', region: 'LEC', pool: 3 },
  { team: '', region: 'LCK', pool: 3 }, { team: '', region: 'LPL', pool: 3 },
  { team: '', region: 'LCP', pool: 4 }, { team: '', region: 'LCK', pool: 4 },
  { team: '', region: 'LPL', pool: 4 },
];

const DIRECT_SLOT_LABELS = [
  'LCK #1', 'LPL #1', 'LCS #1', 'LEC #1',
  'LCP #1', 'CBLOL #1', 'LCK #2', 'LPL #2',
  'LCS #2', 'LEC #2', 'LCK #3', 'LPL #3',
  'LCP #2', 'LCK #4', 'LPL #4',
];

const INITIAL_PLAY_IN_TEAMS: WorldsTeamInput[] = [
  { team: '', region: 'LCS' }, { team: '', region: 'LEC' },
  { team: '', region: 'LCP' }, { team: '', region: 'CBLOL' },
];

const PLAY_IN_SLOT_LABELS = ['LCS #3', 'LEC #3', 'LCP #3', 'CBLOL #2'];

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

  // Worlds slots follow the published Leaguepedia/Fandom 2026 regional allocation.
  const [directWorldsTeams, setDirectWorldsTeams] = useState<WorldsTeamInput[]>(INITIAL_DIRECT_TEAMS);
  const [playInWorldsTeams, setPlayInWorldsTeams] = useState<WorldsTeamInput[]>(INITIAL_PLAY_IN_TEAMS);
  const [worldsData, setWorldsData] = useState<WorldsSimulationResponse | null>(null);
  const [worldsSimulating, setWorldsSimulating] = useState<boolean>(false);

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

  const handleSimulateWorlds = async () => {
    setWorldsSimulating(true);
    try {
      const res = await simulateWorlds(
        directWorldsTeams,
        playInWorldsTeams,
        4,
        5000,
      );
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

  const handleUpdateWorldsTeam = (
    stage: 'direct' | 'playIn',
    index: number,
    value: string,
  ) => {
    const updateTeams = (teams: WorldsTeamInput[]) => teams.map((team, teamIndex) => (
      teamIndex === index ? { ...team, team: value } : team
    ));
    if (stage === 'direct') {
      setDirectWorldsTeams(updateTeams);
    } else {
      setPlayInWorldsTeams(updateTeams);
    }
    setWorldsData(null);
  };

  const worldsReady = [
    ...directWorldsTeams,
    ...playInWorldsTeams,
  ].every((team) => team.team.trim());

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
              disabled={worldsSimulating || !worldsReady}
            >
              {worldsSimulating ? '⏳ Symulacja Worlds...' : '⚡ Symuluj Worlds (5 000 prób)'}
            </button>
            {!worldsReady && (
              <span className="worlds-validation-hint">
                Uzupełnij drużyny dla wszystkich 15 slotów Swiss i 4 slotów Play-In.
              </span>
            )}
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
            <h2>Skład Worlds 2026 — wybierz drużyny do oficjalnych slotów</h2>
            <p className="subtitle-sm">
              Nazwy drużyn pozostają puste. Regiony, seedy i pule są ustawione zgodnie z tabelą uczestników
              Worlds 2026 w Leaguepedia/Fandom; wypełniasz wyłącznie zespół, który zdobędzie dany seed.
            </p>

            <div className="worlds-stage-heading">
              <h3>Swiss — 15 bezpośrednich miejsc</h3>
              <span>Układ slotów Leaguepedia/Fandom</span>
            </div>
            <div className="worlds-pool-grid">
              {[1, 2, 3, 4].map((pool) => (
                <div key={pool} className="worlds-pool-card">
                  <h4>Pula {pool} <span>({pool === 4 ? '3 + Play-In' : '4'})</span></h4>
                  {directWorldsTeams.map((team, index) => (
                    team.pool === pool && (
                      <div key={index} className="worlds-team-slot">
                        <span className="worlds-slot-label">{DIRECT_SLOT_LABELS[index]}</span>
                        <input
                          type="text"
                          value={team.team}
                          onChange={(event) => handleUpdateWorldsTeam('direct', index, event.target.value)}
                          className="team-text-input"
                          placeholder={`Wybierz ${DIRECT_SLOT_LABELS[index]}`}
                          aria-label={`Drużyna Swiss ${index + 1}`}
                        />
                      </div>
                    )
                  ))}
                </div>
              ))}
            </div>

            <div className="worlds-stage-heading">
              <h3>Play-In — 4 zespoły</h3>
              <span>Double elimination Bo5; zwycięzca trafia do puli 4 Swiss</span>
            </div>
            <div className="play-in-grid">
              {playInWorldsTeams.map((team, index) => (
                <div key={index} className="worlds-team-slot">
                  <span className="worlds-slot-label">{PLAY_IN_SLOT_LABELS[index]}</span>
                  <input
                    type="text"
                    value={team.team}
                    onChange={(event) => handleUpdateWorldsTeam('playIn', index, event.target.value)}
                    className="team-text-input"
                    placeholder={`Wybierz ${PLAY_IN_SLOT_LABELS[index]}`}
                    aria-label={`Drużyna Play-In ${index + 1}`}
                  />
                </div>
              ))}
            </div>
            <a
              className="worlds-source-link"
              href="https://lol.fandom.com/wiki/2026_Season_World_Championship"
              target="_blank"
              rel="noreferrer"
            >
              Źródło slotów: Leaguepedia / Fandom — Worlds 2026
            </a>
          </section>

          <section className="worlds-results-panel">
            <h2>🏆 Wyniki Symulacji Worlds 2026</h2>
            {worldsData ? (
              <table className="standings-table">
                <thead>
                  <tr>
                    <th>Drużyna</th>
                    <th>Region / etap</th>
                    <th>Play-In → Swiss</th>
                    <th>🥇 Puchar Worlds</th>
                    <th>🥈 Finał</th>
                    <th>Top 4</th>
                    <th>Swiss Top 8</th>
                  </tr>
                </thead>
                <tbody>
                  {worldsData.standings.map((standing) => (
                    <tr key={standing.team}>
                      <td className="team-cell"><strong>{standing.team}</strong></td>
                      <td className="prob-cell">
                        {standing.region} · {standing.stage === 'play_in' ? 'Play-In' : `Swiss P${standing.pool}`}
                      </td>
                      <td className="prob-cell">{(standing.play_in_qualifier_prob * 100).toFixed(1)}%</td>
                      <td className="prob-cell champ-prob">{(standing.champion_prob * 100).toFixed(1)}%</td>
                      <td className="prob-cell">{(standing.top2_prob * 100).toFixed(1)}%</td>
                      <td className="prob-cell">{(standing.top4_prob * 100).toFixed(1)}%</td>
                      <td className="prob-cell">{(standing.top8_swiss_prob * 100).toFixed(1)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="empty-state">
                <p>Wpisz własne 15 bezpośrednich uczestników i 4 zespoły Play-In. Symulacja obejmie Play-In,
                  Swiss (Bo1/Bo3) oraz pucharową fazę Bo5.</p>
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
