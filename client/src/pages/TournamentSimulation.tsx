import { useEffect, useState } from 'react';
import {
  fetchActiveTeams,
  fetchEncConfiguration,
  fetchTournamentBracket,
  fetchTournaments,
  simulateEnc,
  simulateTournament,
  simulateWorlds,
  syncTournamentBracket,
} from '../api/client';
import type {
  BracketMatch,
  EncConfigurationResponse,
  EncSimulationResponse,
  TournamentSimulationResponse,
  TournamentSummary,
  WorldsSimulationResponse,
  WorldsTeamInput,
} from '../types';
import './TournamentSimulation.css';

const INITIAL_DIRECT_TEAMS: WorldsTeamInput[] = [
  { team: 'Gen.G', region: 'LCK', pool: 1 },
  { team: 'Bilibili Gaming', region: 'LPL', pool: 1 },
  { team: 'LYON', region: 'LCS', pool: 1 },
  { team: 'G2 Esports', region: 'LEC', pool: 1 },
  { team: 'Team Secret Whales', region: 'LCP', pool: 2 },
  { team: 'Los Grandes', region: 'CBLOL', pool: 2 },
  { team: 'Hanwha Life Esports', region: 'LCK', pool: 2 },
  { team: "Anyone's Legend", region: 'LPL', pool: 2 },
  { team: 'Team Liquid', region: 'LCS', pool: 3 },
  { team: 'Karmine Corp', region: 'LEC', pool: 3 },
  { team: 'T1', region: 'LCK', pool: 3 },
  { team: 'Top Esports', region: 'LPL', pool: 3 },
  { team: 'CTBC Flying Oyster', region: 'LCP', pool: 4 },
  { team: 'Dplus KIA', region: 'LCK', pool: 4 },
  { team: 'LGD Gaming', region: 'LPL', pool: 4 },
];

const DIRECT_SLOT_LABELS = [
  'LCK #1', 'LPL #1', 'LCS #1', 'LEC #1',
  'LCP #1', 'CBLOL #1', 'LCK #2', 'LPL #2',
  'LCS #2', 'LEC #2', 'LCK #3', 'LPL #3',
  'LCP #2', 'LCK #4', 'LPL #4',
];

const INITIAL_PLAY_IN_TEAMS: WorldsTeamInput[] = [
  { team: 'Cloud9', region: 'LCS' }, { team: 'GIANTX', region: 'LEC' },
  { team: 'MVK Esports', region: 'LCP' }, { team: 'LOUD', region: 'CBLOL' },
];

const PLAY_IN_SLOT_LABELS = ['LCS #3', 'LEC #3', 'LCP #3', 'CBLOL #2'];

export default function TournamentSimulation() {
  const [activeTab, setActiveTab] = useState<'regional' | 'worlds' | 'enc'>('regional');
  // Layout states for spacious tables and flexible views
  const [regionalLayout, setRegionalLayout] = useState<'split' | 'stacked'>('split');
  const [worldsView, setWorldsView] = useState<'results' | 'editor' | 'split'>('results');
  const [encView, setEncView] = useState<'results' | 'rosters' | 'split'>('results');

  // Regional state
  const [tournaments, setTournaments] = useState<TournamentSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string>('lck_2026_playoffs');
  const [data, setData] = useState<TournamentSimulationResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [simulating, setSimulating] = useState<boolean>(false);
  const [simCount, setSimCount] = useState<number>(10000);
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState<boolean>(false);
  const [syncSource, setSyncSource] = useState<'auto' | 'fandom' | 'liquipedia'>('auto');
  const [syncSuccessMessage, setSyncSuccessMessage] = useState<string | null>(null);
  const [manualModalOpen, setManualModalOpen] = useState<boolean>(false);
  const [manualText, setManualText] = useState<string>('');
  // Worlds slots follow the published Leaguepedia/Fandom 2026 regional allocation.
  const [directWorldsTeams, setDirectWorldsTeams] = useState<WorldsTeamInput[]>(INITIAL_DIRECT_TEAMS);
  const [playInWorldsTeams, setPlayInWorldsTeams] = useState<WorldsTeamInput[]>(INITIAL_PLAY_IN_TEAMS);
  const [worldsData, setWorldsData] = useState<WorldsSimulationResponse | null>(null);
  const [worldsSimulating, setWorldsSimulating] = useState<boolean>(false);
  const [worldsSimCount, setWorldsSimCount] = useState<number>(5000);
  const [activeTeams, setActiveTeams] = useState<Array<{ name: string; rating: number | null }>>([]);
  const [teamSuggestionError, setTeamSuggestionError] = useState<string | null>(null);
  const [activeSuggestionSlot, setActiveSuggestionSlot] = useState<{
    stage: 'direct' | 'playIn';
    index: number;
  } | null>(null);

  const [encConfiguration, setEncConfiguration] = useState<EncConfigurationResponse | null>(null);
  const [encData, setEncData] = useState<EncSimulationResponse | null>(null);
  const [encLoading, setEncLoading] = useState<boolean>(false);
  const [encSimulating, setEncSimulating] = useState<boolean>(false);
  const [encSimCount, setEncSimCount] = useState<number>(1000);
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
    fetchActiveTeams()
      .then((response) => setActiveTeams(response.teams))
      .catch((reason: unknown) => {
        setTeamSuggestionError(
          reason instanceof Error ? reason.message : 'Nie udało się pobrać aktualnych drużyn.',
        );
      });
  }, []);

  useEffect(() => {
    if (activeTab !== 'enc' || encConfiguration || encLoading) return;
    setEncLoading(true);
    fetchEncConfiguration()
      .then(setEncConfiguration)
      .catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : 'Nie udało się pobrać konfiguracji ENC.');
      })
      .finally(() => setEncLoading(false));
  }, [activeTab, encConfiguration, encLoading]);

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

  const handleSyncBracket = async (sourceOverride?: 'auto' | 'fandom' | 'liquipedia') => {
    if (!selectedId) return;
    setSyncing(true);
    setError(null);
    setSyncSuccessMessage(null);
    try {
      const chosenSource = sourceOverride || syncSource;
      const res = await syncTournamentBracket(selectedId, chosenSource, true);
      setData(res);
      setOverrides({});
      if (res.sync_message) {
        setSyncSuccessMessage(res.sync_message);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Błąd synchronizacji drabinki');
    } finally {
      setSyncing(false);
    }
  };

  const handleManualImport = async () => {
    if (!selectedId || !manualText.trim()) return;
    setSyncing(true);
    setError(null);
    try {
      const res = await syncTournamentBracket(selectedId, 'liquipedia', true, manualText);
      setData(res);
      setOverrides({});
      setManualModalOpen(false);
      setManualText('');
      if (res.sync_message) {
        setSyncSuccessMessage(res.sync_message);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Błąd importu ręcznego');
    } finally {
      setSyncing(false);
    }
  };
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
        worldsSimCount,
      );
      setWorldsData(res);
      setWorldsView('results');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Błąd symulacji Worlds');
    } finally {
      setWorldsSimulating(false);
    }
  };

  const handleSimulateEnc = async () => {
    if (!encConfiguration?.simulation_ready) return;
    setEncSimulating(true);
    try {
      const res = await simulateEnc(encSimCount);
      setEncData(res);
      setEncView('results');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Błąd symulacji ENC');
    } finally {
      setEncSimulating(false);
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

  const activeSuggestionValue = activeSuggestionSlot
    ? (activeSuggestionSlot.stage === 'direct'
      ? directWorldsTeams[activeSuggestionSlot.index].team
      : playInWorldsTeams[activeSuggestionSlot.index].team)
    : '';
  const visibleTeamSuggestions = activeTeams
    .filter((team) => team.name.toLocaleLowerCase().includes(activeSuggestionValue.toLocaleLowerCase()))
    .slice(0, 8);

  const handleSelectSuggestedTeam = (
    stage: 'direct' | 'playIn',
    index: number,
    teamName: string,
  ) => {
    handleUpdateWorldsTeam(stage, index, teamName);
    setActiveSuggestionSlot(null);
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
          <button
            className={`tab-btn ${activeTab === 'enc' ? 'active' : ''}`}
            onClick={() => setActiveTab('enc')}
          >
            🏳️ ENC 2027 (reprezentacje)
          </button>
        </div>

        {activeTab === 'regional' ? (
          <>
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
              <div className="layout-toggle-group" role="group" aria-label="Układ widoku regionalnego">
                <button
                  type="button"
                  className={`layout-toggle-btn ${regionalLayout === 'split' ? 'active' : ''}`}
                  onClick={() => setRegionalLayout('split')}
                  title="Widok obok siebie (Szeroka tabela + Drabinka)"
                >
                  ⊞ Obok siebie
                </button>
                <button
                  type="button"
                  className={`layout-toggle-btn ${regionalLayout === 'stacked' ? 'active' : ''}`}
                  onClick={() => setRegionalLayout('stacked')}
                  title="Widok pełnej szerokości (Tabela na górze, Drabinka pod spodem)"
                >
                  ☰ Tabela na górze
                </button>
              </div>
            </div>

            <div className="sync-toolbar">
              <div className="sync-source-group">
                <label>Źródło danych:</label>
                <select
                  value={syncSource}
                  onChange={(e) => setSyncSource(e.target.value as 'auto' | 'fandom' | 'liquipedia')}
                  className="sync-source-select"
                >
                  <option value="auto">⚡ Auto (LoL Fandom / Liquipedia)</option>
                  <option value="fandom">🎮 LoL Fandom Cargo (Live)</option>
                  <option value="liquipedia">📖 Liquipedia MediaWiki</option>
                </select>
              </div>
              <button
                className="sync-btn"
                onClick={() => handleSyncBracket()}
                disabled={syncing || loading}
                title="Pobierz i zaktualizuj bieżący stan meczów, wyników i awansów z wybranego źródła"
              >
                {syncing ? '⏳ Pobieranie z API...' : '🔄 Pobierz stan drabinki'}
              </button>
              <button
                className="manual-import-btn"
                onClick={() => setManualModalOpen(true)}
                title="Wklej ręcznie wikitext szablonu Bracket lub fragment HTML z Liquipedii"
              >
                📋 Import Wikitext / HTML
              </button>
              <div className="sync-status-badges">
                {data?.source && (
                  <span
                    className={`sync-badge ${
                      data.source.includes('fandom')
                        ? 'fandom'
                        : data.source.includes('manual')
                        ? 'manual'
                        : data.source.includes('liquipedia')
                        ? 'liquipedia'
                        : 'cache'
                    }`}
                  >
                    {data.source.includes('fandom')
                      ? '🎮 LoL Fandom (Live)'
                      : data.source.includes('manual')
                      ? '📋 Wikitext/HTML'
                      : data.source.includes('liquipedia')
                      ? '📖 Liquipedia'
                      : '💾 Pamięć podręczna'}
                  </span>
                )}
                {data?.synced_at && (
                  <span className="sync-meta-chip">
                    🕒 Zaktualizowano:{' '}
                    {new Date(data.synced_at).toLocaleTimeString('pl-PL', {
                      hour: '2-digit',
                      minute: '2-digit',
                      second: '2-digit',
                    })}
                  </span>
                )}
                {data?.updated_matches !== undefined && (
                  <span className="sync-meta-chip matches">
                    ✓ Zsynchronizowano {data.updated_matches} meczów
                  </span>
                )}
              </div>
            </div>
          </>
        ) : activeTab === 'worlds' ? (
          <div className="tournament-controls">
            <div className="sim-config">
              <label htmlFor="worlds-simulation-count">Próby Worlds:</label>
              <select
                id="worlds-simulation-count"
                value={worldsSimCount}
                onChange={(event) => setWorldsSimCount(Number(event.target.value))}
                className="sim-count-select"
              >
                <option value={1000}>1 000</option>
                <option value={5000}>5 000</option>
                <option value={10000}>10 000</option>
                <option value={20000}>20 000</option>
              </select>
            </div>
            <button
              className="simulate-btn"
              onClick={handleSimulateWorlds}
              disabled={worldsSimulating || !worldsReady}
            >
              {worldsSimulating
                ? '⏳ Symulacja Worlds...'
                : `⚡ Symuluj Worlds (${worldsSimCount.toLocaleString('pl-PL')} prób)`}
            </button>
            <div className="simulation-subtabs" role="group" aria-label="Widok Worlds">
              <button
                type="button"
                className={`subtab-btn ${worldsView === 'results' ? 'active' : ''}`}
                onClick={() => setWorldsView('results')}
              >
                📊 Tabela wyników
              </button>
              <button
                type="button"
                className={`subtab-btn ${worldsView === 'editor' ? 'active' : ''}`}
                onClick={() => setWorldsView('editor')}
              >
                ⚙️ Edytor slotów
              </button>
              <button
                type="button"
                className={`subtab-btn ${worldsView === 'split' ? 'active' : ''}`}
                onClick={() => setWorldsView('split')}
              >
                ⊞ Obok siebie
              </button>
            </div>
            {!worldsReady && (
              <span className="worlds-validation-hint">
                Uzupełnij drużyny dla wszystkich 15 slotów Swiss i 4 slotów Play-In.
              </span>
            )}
          </div>
        ) : (
          <div className="tournament-controls">
            <div className="sim-config">
              <label htmlFor="enc-simulation-count">Próby ENC:</label>
              <select
                id="enc-simulation-count"
                value={encSimCount}
                onChange={(event) => setEncSimCount(Number(event.target.value))}
                className="sim-count-select"
              >
                <option value={1000}>1 000</option>
                <option value={5000}>5 000</option>
                <option value={10000}>10 000</option>
                <option value={20000}>20 000</option>
              </select>
            </div>
            <button
              className="simulate-btn"
              onClick={handleSimulateEnc}
              disabled={encSimulating || !encConfiguration?.simulation_ready}
            >
            {encSimulating ? '⏳ Symulacja ENC...' : `⚡ Symuluj ENC (${encSimCount.toLocaleString('pl-PL')} prób)`}
            </button>
            <div className="simulation-subtabs" role="group" aria-label="Widok ENC">
              <button
                type="button"
                className={`subtab-btn ${encView === 'results' ? 'active' : ''}`}
                onClick={() => setEncView('results')}
              >
                🏆 Tabela wyników
              </button>
              <button
                type="button"
                className={`subtab-btn ${encView === 'rosters' ? 'active' : ''}`}
                onClick={() => setEncView('rosters')}
              >
                👥 Składy nacji
              </button>
              <button
                type="button"
                className={`subtab-btn ${encView === 'split' ? 'active' : ''}`}
                onClick={() => setEncView('split')}
              >
                ⊞ Obok siebie
              </button>
            </div>
          </div>
        )}
      </header>
      {syncSuccessMessage && (
        <div className="sync-success-banner">
          <div className="banner-content">
            <span className="banner-icon">✓</span>
            <span>{syncSuccessMessage}</span>
          </div>
          <button className="banner-close-btn" onClick={() => setSyncSuccessMessage(null)}>
            ✕
          </button>
        </div>
      )}

      {manualModalOpen && (
        <div className="modal-backdrop" onClick={() => setManualModalOpen(false)}>
          <div className="modal-dialog" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>📋 Ręczny import stanu drabinki (Liquipedia / LoL Fandom)</h3>
              <button className="modal-close" onClick={() => setManualModalOpen(false)}>
                ✕
              </button>
            </div>
            <div className="modal-body">
              <p className="modal-hint">
                Wklej kod źródłowy szablonu drabinki (np. <code>{'{{Bracket|r1m1team1=...}}'}</code>) lub tabelę
                HTML skopiowaną ze strony Liquipedii.
              </p>
              <textarea
                className="manual-textarea"
                placeholder="Wklej kod wikitext lub HTML tutaj..."
                value={manualText}
                onChange={(e) => setManualText(e.target.value)}
                rows={10}
              />
            </div>
            <div className="modal-footer">
              <button className="btn-secondary" onClick={() => setManualModalOpen(false)}>
                Anuluj
              </button>
              <button
                className="btn-primary"
                onClick={handleManualImport}
                disabled={syncing || !manualText.trim()}
              >
                {syncing ? 'Przetwarzanie...' : 'Zastosuj do drabinki'}
              </button>
            </div>
          </div>
        </div>
      )}

      {error && <div className="error-banner">{error}</div>}

      {activeTab === 'regional' ? (
        <div className={`simulation-layout ${regionalLayout}`}>
          <section className={`standings-panel ${regionalLayout === 'stacked' ? 'full-width' : ''}`}>
            <div className="standings-panel-header">
              <h2>📊 Szanse na końcowy wynik ({data?.simulations.toLocaleString('pl-PL')} symulacji)</h2>
            </div>
            <div className="table-responsive">
              <table className="standings-table">
                <thead>
                  <tr>
                    <th className="th-rank">Poz.</th>
                    <th className="th-team">Drużyna</th>
                    <th className="th-num">🥇 Mistrz</th>
                    <th className="th-num">🥈 Top 2</th>
                    <th className="th-num">🥉 Top 3</th>
                    <th className="th-num">Top 4</th>
                  </tr>
                </thead>
                <tbody>
                  {data?.standings.map((s, idx) => (
                    <tr key={s.team}>
                      <td className="rank-cell">{idx + 1}</td>
                      <td className="team-cell"><strong>{s.team}</strong></td>
                      <td className="prob-cell champ-prob">
                        <div className="prob-with-bar">
                          <div className="mini-bar-bg">
                            <div className="mini-bar-fill gold" style={{ width: `${Math.min(100, s.champion_prob * 100)}%` }} />
                          </div>
                          <span>{(s.champion_prob * 100).toFixed(1)}%</span>
                        </div>
                      </td>
                      <td className="prob-cell">{(s.top2_prob * 100).toFixed(1)}%</td>
                      <td className="prob-cell">{(s.top3_prob * 100).toFixed(1)}%</td>
                      <td className="prob-cell">{(s.top4_prob * 100).toFixed(1)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="scenario-tip">
              💡 <strong>Tryb scenariuszy (What-if):</strong> Kliknij na dowolną drużynę w drabince, aby wymusić jej zwycięstwo i przeliczyć resztę turnieju.
            </p>
          </section>

          <section className={`bracket-panel ${regionalLayout === 'stacked' ? 'full-width' : ''}`}>
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
      ) : activeTab === 'worlds' ? (
        <div className={`worlds-layout ${worldsView}`}>
          {(worldsView === 'editor' || worldsView === 'split') && (
            <section className={`worlds-teams-editor ${worldsView === 'editor' ? 'full-width' : ''}`}>
            <h2>Skład Worlds 2026 — wybierz drużyny do oficjalnych slotów</h2>
            <p className="subtitle-sm">
              Wstępnie wypełnione zespoły odpowiadają slotom Leaguepedia/Fandom. Możesz je zmienić przed
              symulacją; regiony, seedy i pule pozostają zgodne z opublikowaną strukturą Worlds 2026.
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
                        <div className="worlds-suggestion-container">
                          <input
                            type="text"
                            value={team.team}
                            onChange={(event) => handleUpdateWorldsTeam('direct', index, event.target.value)}
                            onFocus={() => setActiveSuggestionSlot({ stage: 'direct', index })}
                            onBlur={() => {
                              window.setTimeout(() => {
                                setActiveSuggestionSlot((current) => (
                                  current?.stage === 'direct' && current.index === index ? null : current
                                ));
                              }, 150);
                            }}
                            className="team-text-input"
                            placeholder={`Wybierz ${DIRECT_SLOT_LABELS[index]}`}
                            aria-label={`Drużyna Swiss ${index + 1}`}
                            autoComplete="off"
                          />
                          {activeSuggestionSlot?.stage === 'direct'
                            && activeSuggestionSlot.index === index
                            && visibleTeamSuggestions.length > 0 && (
                              <div className="worlds-suggestion-menu" role="listbox">
                                {visibleTeamSuggestions.map((suggestion) => (
                                  <button
                                    key={suggestion.name}
                                    type="button"
                                    className="worlds-suggestion-option"
                                    onMouseDown={(event) => event.preventDefault()}
                                    onClick={() => handleSelectSuggestedTeam('direct', index, suggestion.name)}
                                  >
                                    <span>{suggestion.name}</span>
                                    {suggestion.rating !== null && <small>GL {Math.round(suggestion.rating)}</small>}
                                  </button>
                                ))}
                              </div>
                            )}
                        </div>
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
                  <div className="worlds-suggestion-container">
                    <input
                      type="text"
                      value={team.team}
                      onChange={(event) => handleUpdateWorldsTeam('playIn', index, event.target.value)}
                      onFocus={() => setActiveSuggestionSlot({ stage: 'playIn', index })}
                      onBlur={() => {
                        window.setTimeout(() => {
                          setActiveSuggestionSlot((current) => (
                            current?.stage === 'playIn' && current.index === index ? null : current
                          ));
                        }, 150);
                      }}
                      className="team-text-input"
                      placeholder={`Wybierz ${PLAY_IN_SLOT_LABELS[index]}`}
                      aria-label={`Drużyna Play-In ${index + 1}`}
                      autoComplete="off"
                    />
                    {activeSuggestionSlot?.stage === 'playIn'
                      && activeSuggestionSlot.index === index
                      && visibleTeamSuggestions.length > 0 && (
                        <div className="worlds-suggestion-menu" role="listbox">
                          {visibleTeamSuggestions.map((suggestion) => (
                            <button
                              key={suggestion.name}
                              type="button"
                              className="worlds-suggestion-option"
                              onMouseDown={(event) => event.preventDefault()}
                              onClick={() => handleSelectSuggestedTeam('playIn', index, suggestion.name)}
                            >
                              <span>{suggestion.name}</span>
                              {suggestion.rating !== null && <small>GL {Math.round(suggestion.rating)}</small>}
                            </button>
                          ))}
                        </div>
                      )}
                  </div>
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
            {activeTeams.length > 0 && (
              <p className="worlds-suggestion-note">
                Podpowiedzi: {activeTeams.length} aktualnych drużyn z operacyjnego rankingu GL.
              </p>
            )}
            {teamSuggestionError && (
              <p className="worlds-suggestion-error">{teamSuggestionError}</p>
            )}
            </section>
          )}

          {(worldsView === 'results' || worldsView === 'split') && (
            <section className={`worlds-results-panel ${worldsView === 'results' ? 'full-width' : ''}`}>
              <div className="results-panel-header">
                <div>
                  <h2>🏆 Wyniki Symulacji Worlds 2026</h2>
                  {worldsData && (
                    <p className="subtitle-sm">
                      Symulacja Monte Carlo ({worldsData.simulations.toLocaleString('pl-PL')} prób): Play-In Bo5, Swiss Bo1/Bo3 i puchar Bo5.
                    </p>
                  )}
                </div>
                {worldsData && worldsView === 'results' && (
                  <button
                    type="button"
                    className="ghost-action-btn"
                    onClick={() => setWorldsView('editor')}
                  >
                    ✏️ Edytuj sloty drużyn
                  </button>
                )}
              </div>
              {worldsData ? (
                <>
                  <div className="summary-cards-grid">
                    <div className="summary-card gold-border">
                      <span className="card-label">Główny faworyt</span>
                      <strong className="card-value">{worldsData.standings[0]?.team || '—'}</strong>
                      <span className="card-sub">
                        {((worldsData.standings[0]?.champion_prob || 0) * 100).toFixed(1)}% szans na mistrzostwo
                      </span>
                    </div>
                    <div className="summary-card silver-border">
                      <span className="card-label">Drugi pretendent</span>
                      <strong className="card-value">{worldsData.standings[1]?.team || '—'}</strong>
                      <span className="card-sub">
                        {((worldsData.standings[1]?.champion_prob || 0) * 100).toFixed(1)}% mistrz · {((worldsData.standings[1]?.top2_prob || 0) * 100).toFixed(1)}% finał
                      </span>
                    </div>
                    <div className="summary-card">
                      <span className="card-label">Uczestnicy</span>
                      <strong className="card-value">{worldsData.standings.length} zespołów</strong>
                      <span className="card-sub">15 Swiss + 4 Play-In</span>
                    </div>
                    <div className="summary-card">
                      <span className="card-label">Liczba symulacji</span>
                      <strong className="card-value">{worldsData.simulations.toLocaleString('pl-PL')}</strong>
                      <span className="card-sub">Format Riot 2026</span>
                    </div>
                  </div>

                  <div className="table-responsive">
                    <table className="standings-table">
                      <thead>
                        <tr>
                          <th className="th-rank">Poz.</th>
                          <th className="th-team">Drużyna</th>
                          <th className="th-meta">Region i etap</th>
                          <th className="th-num">Play-In → Swiss</th>
                          <th className="th-num">🥇 Puchar Worlds</th>
                          <th className="th-num">🥈 Finał</th>
                          <th className="th-num">Top 4</th>
                          <th className="th-num">Swiss Top 8</th>
                        </tr>
                      </thead>
                      <tbody>
                        {worldsData.standings.map((standing, idx) => (
                          <tr key={standing.team}>
                            <td className="rank-cell">{idx + 1}</td>
                            <td className="team-cell"><strong>{standing.team}</strong></td>
                            <td className="meta-cell">
                              <span className="badge region-badge">{standing.region}</span>
                              <span className="badge stage-badge">
                                {standing.stage === 'play_in' ? 'Play-In' : `Swiss P${standing.pool}`}
                              </span>
                            </td>
                            <td className="prob-cell">{(standing.play_in_qualifier_prob * 100).toFixed(1)}%</td>
                            <td className="prob-cell champ-prob">
                              <div className="prob-with-bar">
                                <div className="mini-bar-bg">
                                  <div
                                    className="mini-bar-fill gold"
                                    style={{ width: `${Math.min(100, standing.champion_prob * 100)}%` }}
                                  />
                                </div>
                                <span>{(standing.champion_prob * 100).toFixed(1)}%</span>
                              </div>
                            </td>
                            <td className="prob-cell">{(standing.top2_prob * 100).toFixed(1)}%</td>
                            <td className="prob-cell">{(standing.top4_prob * 100).toFixed(1)}%</td>
                            <td className="prob-cell">{(standing.top8_swiss_prob * 100).toFixed(1)}%</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              ) : (
                <div className="empty-state">
                  <p>
                    Wpisz własne 15 bezpośrednich uczestników i 4 zespoły Play-In (lub skorzystaj z gotowych slotów Fandom).
                    Kliknij <strong>⚡ Symuluj Worlds</strong> w pasku powyżej, aby wygenerować pełną tabelę wyników.
                  </p>
                  {worldsView === 'results' && (
                    <button
                      type="button"
                      className="ghost-action-btn"
                      style={{ marginTop: '1rem' }}
                      onClick={() => setWorldsView('editor')}
                    >
                      ⚙️ Otwórz edytor slotów drużyn
                    </button>
                  )}
                </div>
              )}
            </section>
          )}
        </div>
      ) : (
        <div className={`enc-layout ${encView}`}>
          {(encView === 'rosters' || encView === 'split') && (
            <section className={`enc-rosters-panel ${encView === 'rosters' ? 'full-width' : ''}`}>
            <h2>ENC 2027 — najwyższy aktualny GL w roli z Fandom</h2>
            {encLoading && <div className="empty-state"><p>Ładowanie składów i snapshotu GL...</p></div>}
            {encConfiguration && (
              <>
                <p className="subtitle-sm">
                  Każda rola wybiera najwyższy rating GL wyłącznie wśród zawodników przypisanych do niej w publicznej tabeli kadry Fandom.
                  Zawodnik bez wpisu GL dostaje jawny rating domyślny {encConfiguration.default_rating.toFixed(1)}; średnia pięciu ról jest wskaźnikiem
                  siły kadry, nie predykcją modelu EXP-039.
                </p>
                <div className="enc-format-grid">
                  <div><strong>Play-In</strong><span>{encConfiguration.format.play_in}</span></div>
                  <div><strong>Group Stage</strong><span>{encConfiguration.format.group_stage}</span></div>
                  <div><strong>Playoffs</strong><span>{encConfiguration.format.playoffs}</span></div>
                </div>
                {!encConfiguration.simulation_ready && (
                  <div className="enc-blocking-issues">
                    <strong>Symulacja wymaga przypisania wszystkich pięciu ról.</strong>
                    <ul>{encConfiguration.blocking_issues.map((issue) => <li key={issue}>{issue}</li>)}</ul>
                  </div>
                )}
                {encConfiguration.teams.some((team) => (
                  team.selected_roster.some((player) => player.rating_source === 'default')
                )) && (
                  <p className="enc-default-note">
                    <strong>GL domyślny {encConfiguration.default_rating.toFixed(1)}:</strong> użyty wyłącznie tam, gdzie ogłoszony zawodnik nie ma
                    aktualnego wpisu GL. Wiersze są oznaczone „domyślny”.
                  </p>
                )}
                <a
                  className="worlds-source-link"
                  href={encConfiguration.source_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  Źródło struktury i kadr: Leaguepedia / Fandom — Esports Nations Cup 2027
                </a>
                <p className="enc-draw-note">{encConfiguration.format.draw_and_tiebreak_policy}</p>
                <div className="enc-team-grid">
                  {encConfiguration.teams.map((team) => (
                    <article key={team.nation} className={`enc-team-card ${team.selection_status}`}>
                      <div className="enc-team-heading">
                        <h3>{team.nation}</h3>
                        <span>{team.entry_stage === 'group_stage' ? 'bezpośrednio Group Stage' : 'Play-In'}</span>
                      </div>
                      {team.ranking !== null && <p className="enc-ranking">Ranking zaproszeń #{team.ranking}</p>}
                      {team.selected_roster.map((player) => (
                        <div className="enc-player-row" key={player.role}>
                          <span>{player.role}</span>
                          <strong>{player.player}</strong>
                          <small>
                            GL {player.rating.toFixed(1)}
                            {player.rating_source === 'default' ? ' · domyślny' : ''}
                          </small>
                        </div>
                      ))}
                      {team.missing_roles.length > 0 && (
                        <p className="enc-missing-roles">Brak ratingu/roli: {team.missing_roles.join(', ')}</p>
                      )}
                      {team.roster_rating !== null && <p className="enc-roster-rating">Średnia GL: {team.roster_rating.toFixed(1)}</p>}
                      {team.source_roster.length > 0 && (
                        <details>
                          <summary>Ogłoszona kadra ({team.source_roster.length})</summary>
                          <p>{team.source_roster.join(' · ')}</p>
                        </details>
                      )}
                    </article>
                  ))}
                </div>
              </>
            )}
            </section>
          )}

          {(encView === 'results' || encView === 'split') && (
            <section className={`enc-results-panel ${encView === 'results' ? 'full-width' : ''}`}>
              <div className="results-panel-header">
                <div>
                  <h2>🏆 Wyniki ENC 2027</h2>
                  {encData && (
                    <p className="subtitle-sm">
                      Symulacja Monte Carlo ({encData.simulations.toLocaleString('pl-PL')} prób): Play-In Bo1, grupy Bo3 i puchar Bo3/Bo5.
                    </p>
                  )}
                </div>
                {encData && encView === 'results' && (
                  <button
                    type="button"
                    className="ghost-action-btn"
                    onClick={() => setEncView('rosters')}
                  >
                    👥 Zobacz składy 16 reprezentacji
                  </button>
                )}
              </div>
              {encData ? (
                <>
                  <div className="summary-cards-grid">
                    <div className="summary-card gold-border">
                      <span className="card-label">Główny faworyt ENC</span>
                      <strong className="card-value">{encData.standings[0]?.nation || '—'}</strong>
                      <span className="card-sub">
                        {((encData.standings[0]?.champion_prob || 0) * 100).toFixed(1)}% mistrz · GL {encData.standings[0]?.roster_rating.toFixed(1)}
                      </span>
                    </div>
                    <div className="summary-card silver-border">
                      <span className="card-label">Drugi pretendent / Finał</span>
                      <strong className="card-value">{encData.standings[1]?.nation || '—'}</strong>
                      <span className="card-sub">
                        {((encData.standings[1]?.champion_prob || 0) * 100).toFixed(1)}% mistrz · {((encData.standings[1]?.top2_prob || 0) * 100).toFixed(1)}% finał
                      </span>
                    </div>
                    <div className="summary-card">
                      <span className="card-label">Reprezentacje</span>
                      <strong className="card-value">{encData.standings.length} nacji</strong>
                      <span className="card-sub">Oficjalny format Fandom</span>
                    </div>
                    <div className="summary-card">
                      <span className="card-label">Próby Monte Carlo</span>
                      <strong className="card-value">{encData.simulations.toLocaleString('pl-PL')}</strong>
                      <span className="card-sub">Play-In → Grupy Bo3 → Puchar</span>
                    </div>
                  </div>

                  <div className="table-responsive">
                    <table className="standings-table">
                      <thead>
                        <tr>
                          <th className="th-rank">Poz.</th>
                          <th className="th-team">Reprezentacja</th>
                          <th className="th-meta">Etap wejścia</th>
                          <th className="th-rating">GL składu</th>
                          <th className="th-num">🥇 Mistrz ENC</th>
                          <th className="th-num">🥈 Finał</th>
                          <th className="th-num">Top 4</th>
                          <th className="th-num">Playoffs</th>
                          <th className="th-num">Group Stage</th>
                        </tr>
                      </thead>
                      <tbody>
                        {encData.standings.map((standing, idx) => (
                          <tr key={standing.nation}>
                            <td className="rank-cell">{idx + 1}</td>
                            <td className="team-cell"><strong>{standing.nation}</strong></td>
                            <td className="meta-cell">
                              <span className={`badge ${standing.entry_stage === 'group_stage' ? 'stage-group-badge' : 'stage-playin-badge'}`}>
                                {standing.entry_stage === 'group_stage' ? 'Faza grupowa' : 'Play-In'}
                              </span>
                            </td>
                            <td className="rating-cell">
                              <span className="rating-badge">{standing.roster_rating.toFixed(1)}</span>
                            </td>
                            <td className="prob-cell champ-prob">
                              <div className="prob-with-bar">
                                <div className="mini-bar-bg">
                                  <div
                                    className="mini-bar-fill gold"
                                    style={{ width: `${Math.min(100, standing.champion_prob * 100)}%` }}
                                  />
                                </div>
                                <span>{(standing.champion_prob * 100).toFixed(1)}%</span>
                              </div>
                            </td>
                            <td className="prob-cell">{(standing.top2_prob * 100).toFixed(1)}%</td>
                            <td className="prob-cell">{(standing.top4_prob * 100).toFixed(1)}%</td>
                            <td className="prob-cell">{(standing.playoff_prob * 100).toFixed(1)}%</td>
                            <td className="prob-cell">{(standing.group_stage_prob * 100).toFixed(1)}%</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              ) : (
                <div className="empty-state">
                  <p>
                    Uruchom symulację, aby rozegrać cztery grupy Play-In Bo1, cztery grupy główne Bo3 i puchar
                    Bo3/Bo5 zgodnie z opublikowanym formatem.
                  </p>
                  {encView === 'results' && (
                    <button
                      type="button"
                      className="ghost-action-btn"
                      style={{ marginTop: '1rem' }}
                      onClick={() => setEncView('rosters')}
                    >
                      👥 Otwórz składy reprezentacji
                    </button>
                  )}
                </div>
              )}
            </section>
          )}
        </div>
      )}
    </div>
  );
}
