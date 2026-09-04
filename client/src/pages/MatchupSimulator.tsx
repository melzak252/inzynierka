import { useState, useEffect } from 'react';
import { fetchActiveTeams, simulateMatchup } from '../api/client';
import type { MatchupSimulationResponse } from '../types';
import './MatchupSimulator.css';

interface TeamOption {
  name: string;
  rating: number | null;
  games?: number;
  last_active?: string;
}

const DEFAULT_CURRENT_TEAMS: TeamOption[] = [
  { name: 'T1', rating: 1890 },
  { name: 'Gen.G', rating: 1915 },
  { name: 'Bilibili Gaming', rating: 1880 },
  { name: 'Hanwha Life Esports', rating: 1870 },
  { name: 'Top Esports', rating: 1840 },
  { name: 'G2 Esports', rating: 1760 },
  { name: 'Fnatic', rating: 1710 },
  { name: 'FlyQuest', rating: 1730 },
  { name: 'Team Liquid', rating: 1705 },
  { name: 'Cloud9', rating: 1690 },
  { name: 'Weibo Gaming', rating: 1810 },
  { name: 'Dplus KIA', rating: 1800 },
  { name: 'JD Gaming', rating: 1790 },
  { name: 'KT Rolster', rating: 1750 },
  { name: 'Kwangdong Freecs', rating: 1670 },
  { name: 'Nongshim RedForce', rating: 1640 },
  { name: 'FearX', rating: 1650 },
];

export default function MatchupSimulator() {
  const [activeTeams, setActiveTeams] = useState<TeamOption[]>(DEFAULT_CURRENT_TEAMS);
  const [teamA, setTeamA] = useState('T1');
  const [teamB, setTeamB] = useState('Gen.G');
  const [bestOf, setBestOf] = useState<number>(3);
  const [loadingTeams, setLoadingTeams] = useState(false);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<MatchupSimulationResponse | null>(null);

  // Load active current teams on mount
  useEffect(() => {
    setLoadingTeams(true);
    fetchActiveTeams()
      .then((res) => {
        if (res?.teams?.length) {
          setActiveTeams(res.teams);
        }
      })
      .catch(() => {
        // Fallback to DEFAULT_CURRENT_TEAMS
      })
      .finally(() => {
        setLoadingTeams(false);
      });
  }, []);

  const handleSimulate = async (nameA = teamA, nameB = teamB, bo = bestOf) => {
    if (!nameA.trim() || !nameB.trim()) {
      setError('Wybierz obie drużyny.');
      return;
    }
    if (nameA === nameB) {
      setError('Wybierz dwie różne drużyny do zestawienia.');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const data = await simulateMatchup({
        team_a_name: nameA,
        team_b_name: nameB,
        best_of: bo,
      });
      setResult(data);
    } catch (err: unknown) {
      setError(err instanceof Error && err.message ? err.message : 'Błąd podczas symulacji starcia.');
    } finally {
      setLoading(false);
    }
  };

  // Run automatically when team A, team B or bestOf changes
  useEffect(() => {
    handleSimulate(teamA, teamB, bestOf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [teamA, teamB, bestOf]);

  const swapTeams = () => {
    const temp = teamA;
    setTeamA(teamB);
    setTeamB(temp);
  };

  return (
    <div className="matchup-page">
      <header className="matchup-header">
        <p className="eyebrow">Symulator starć bezpośrednich</p>
        <h1>Matchup Simulator (H2H)</h1>
        <p className="subtitle">
          Wybierz aktywne drużyny z profesjonalnej sceny, ustaw format serii i sprawdź bezpośrednią predykcję modelu oraz zestawienie aktualnych składów 5v5.
        </p>
      </header>

      <section className="matchup-controls-card">
        <div className="matchup-dropdowns-row">
          <div className="team-select-container">
            <label htmlFor="select-team-a">Drużyna A (Niebieska / Gospodarz)</label>
            <div className="select-wrapper">
              <select
                id="select-team-a"
                value={teamA}
                onChange={(e) => setTeamA(e.target.value)}
                disabled={loadingTeams}
              >
                {activeTeams.map((t) => (
                  <option key={`a-${t.name}`} value={t.name}>
                    {t.name} {t.rating ? `(Glicko ${Math.round(t.rating)})` : ''}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <button
            type="button"
            className="swap-teams-btn"
            onClick={swapTeams}
            title="Zamień strony"
            aria-label="Zamień strony"
          >
            ⇄
          </button>

          <div className="team-select-container">
            <label htmlFor="select-team-b">Drużyna B (Czerwona / Gość)</label>
            <div className="select-wrapper">
              <select
                id="select-team-b"
                value={teamB}
                onChange={(e) => setTeamB(e.target.value)}
                disabled={loadingTeams}
              >
                {activeTeams.map((t) => (
                  <option key={`b-${t.name}`} value={t.name}>
                    {t.name} {t.rating ? `(Glicko ${Math.round(t.rating)})` : ''}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>

        <div className="matchup-options-bar">
          <div className="format-selection-group">
            <span className="label">Format serii:</span>
            <div className="bo-pills">
              {[1, 3, 5, 7].map((b) => (
                <button
                  key={b}
                  type="button"
                  className={`pill-btn ${bestOf === b ? 'active' : ''}`}
                  onClick={() => setBestOf(b)}
                >
                  Bo{b}
                </button>
              ))}
            </div>
          </div>

          <div className="quick-info">
            {loading ? (
              <span className="status-loading">⏳ Obliczanie predykcji...</span>
            ) : (
              <span className="status-ready">Model: Operational-PlayerTeamRatings-W20 v0.4</span>
            )}
          </div>
        </div>

        {error && <div className="matchup-error">{error}</div>}
      </section>

      {result && (
        <section className="matchup-view-section">
          {/* Main probability banner */}
          <div className="matchup-hero-card">
            <div className="team-hero-box left">
              <span className="side-indicator">Niebiescy (Blue)</span>
              <h2>{result.team_a_name}</h2>
              <div className="prob-big">{(result.series_prob_a * 100).toFixed(1)}%</div>
              <div className="prob-sub">Pojedyncza mapa: {(result.map_prob_a * 100).toFixed(1)}%</div>
            </div>

            <div className="vs-center-col">
              <div className="series-pill">Seria Bo{result.best_of}</div>
              <div className="h2h-bar">
                <div
                  className="bar-fill-a"
                  style={{ width: `${result.series_prob_a * 100}%` }}
                />
              </div>
              <span className="binomial-formula-hint">Rzutowanie dwumianowe (Binomial Tail)</span>
            </div>

            <div className="team-hero-box right">
              <span className="side-indicator">Czerwoni (Red)</span>
              <h2>{result.team_b_name}</h2>
              <div className="prob-big red">{(result.series_prob_b * 100).toFixed(1)}%</div>
              <div className="prob-sub">Pojedyncza mapa: {(result.map_prob_b * 100).toFixed(1)}%</div>
            </div>
          </div>

          {/* Model Weights Breakdown */}
          <div className="breakdown-cards-row">
            <div className="breakdown-card">
              <span className="bd-title">Ratingi zawodników (70%)</span>
              <strong className="bd-metric">
                {typeof result.components.player_rating_consensus === 'number'
                  ? `${(result.components.player_rating_consensus * 100).toFixed(1)}%`
                  : '50.0%'}
              </strong>
              <small className="bd-desc">Średnia siła 5 graczy z Glicko-2</small>
            </div>
            <div className="breakdown-card">
              <span className="bd-title">Ratingi zespołowe (20%)</span>
              <strong className="bd-metric">
                {typeof result.components.team_rating_consensus === 'number'
                  ? `${(result.components.team_rating_consensus * 100).toFixed(1)}%`
                  : '50.0%'}
              </strong>
              <small className="bd-desc">Stabilność organizacji i synergia</small>
            </div>
            <div className="breakdown-card">
              <span className="bd-title">Forma W20 (10%)</span>
              <strong className="bd-metric">
                {typeof result.components.w20_probability === 'number'
                  ? `${(result.components.w20_probability * 100).toFixed(1)}%`
                  : '50.0%'}
              </strong>
              <small className="bd-desc">Kroczące statystyki z ostatnich 20 gier</small>
            </div>
          </div>

          {/* Rosters comparison - PROMINENT 5v5 VIEW */}
          <div className="rosters-comparison-container">
            <div className="roster-block">
              <div className="roster-header">
                <div>
                  <h3>Skład {result.team_a_name}</h3>
                  <p className="roster-meta">
                    Średni Glicko: <strong>{result.roster_a?.avg_glicko ? Math.round(result.roster_a.avg_glicko) : '—'}</strong>
                    {result.roster_a?.avg_glicko_rd ? ` (RD ±${Math.round(result.roster_a.avg_glicko_rd)})` : ''}
                  </p>
                </div>
              </div>
              <div className="roster-table">
                <div className="roster-row-header">
                  <span>Rola</span>
                  <span>Zawodnik</span>
                  <span className="text-right">Glicko</span>
                  <span className="text-right">Pewność (RD)</span>
                </div>
                {result.roster_a?.players?.length ? (
                  result.roster_a.players.map((player, idx) => (
                    <div className="roster-row" key={`ra-${idx}`}>
                      <span className={`role-badge ${player.role?.toLowerCase()}`}>{player.role || '—'}</span>
                      <span className="player-title">{player.player_name || 'Nieznany'}</span>
                      <span className="player-rating text-right">
                        {player.glicko_rating ? Math.round(player.glicko_rating) : '—'}
                      </span>
                      <span className="player-rd text-right">
                        {player.glicko_rd ? `±${Math.round(player.glicko_rd)}` : '—'}
                      </span>
                    </div>
                  ))
                ) : (
                  <div className="no-roster-msg">Brak zapisanego składu w bazie</div>
                )}
              </div>
            </div>

            <div className="roster-block">
              <div className="roster-header">
                <div>
                  <h3>Skład {result.team_b_name}</h3>
                  <p className="roster-meta">
                    Średni Glicko: <strong>{result.roster_b?.avg_glicko ? Math.round(result.roster_b.avg_glicko) : '—'}</strong>
                    {result.roster_b?.avg_glicko_rd ? ` (RD ±${Math.round(result.roster_b.avg_glicko_rd)})` : ''}
                  </p>
                </div>
              </div>
              <div className="roster-table">
                <div className="roster-row-header">
                  <span>Rola</span>
                  <span>Zawodnik</span>
                  <span className="text-right">Glicko</span>
                  <span className="text-right">Pewność (RD)</span>
                </div>
                {result.roster_b?.players?.length ? (
                  result.roster_b.players.map((player, idx) => (
                    <div className="roster-row" key={`rb-${idx}`}>
                      <span className={`role-badge ${player.role?.toLowerCase()}`}>{player.role || '—'}</span>
                      <span className="player-title">{player.player_name || 'Nieznany'}</span>
                      <span className="player-rating text-right">
                        {player.glicko_rating ? Math.round(player.glicko_rating) : '—'}
                      </span>
                      <span className="player-rd text-right">
                        {player.glicko_rd ? `±${Math.round(player.glicko_rd)}` : '—'}
                      </span>
                    </div>
                  ))
                ) : (
                  <div className="no-roster-msg">Brak zapisanego składu w bazie</div>
                )}
              </div>
            </div>
          </div>
        </section>
      )}
    </div>
  );
}
