import { useState, useEffect } from 'react';
import { searchGolggTeams, simulateMatchup } from '../api/client';
import type { MatchupSimulationResponse } from '../types';
import './MatchupSimulator.css';

export default function MatchupSimulator() {
  const [teamA, setTeamA] = useState('T1');
  const [teamB, setTeamB] = useState('Gen.G');
  const [bestOf, setBestOf] = useState<number>(3);
  const [league, setLeague] = useState('LCK');

  const [candidatesA, setCandidatesA] = useState<string[]>([]);
  const [candidatesB, setCandidatesB] = useState<string[]>([]);
  const [searchingA, setSearchingA] = useState(false);
  const [searchingB, setSearchingB] = useState(false);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<MatchupSimulationResponse | null>(null);

  // Search autocomplete for Team A
  useEffect(() => {
    if (!teamA.trim() || teamA.length < 2) {
      setCandidatesA([]);
      return;
    }
    const timer = setTimeout(async () => {
      setSearchingA(true);
      try {
        const res = await searchGolggTeams(teamA, 6);
        setCandidatesA(res.teams);
      } catch {
        setCandidatesA([]);
      } finally {
        setSearchingA(false);
      }
    }, 250);
    return () => clearTimeout(timer);
  }, [teamA]);

  // Search autocomplete for Team B
  useEffect(() => {
    if (!teamB.trim() || teamB.length < 2) {
      setCandidatesB([]);
      return;
    }
    const timer = setTimeout(async () => {
      setSearchingB(true);
      try {
        const res = await searchGolggTeams(teamB, 6);
        setCandidatesB(res.teams);
      } catch {
        setCandidatesB([]);
      } finally {
        setSearchingB(false);
      }
    }, 250);
    return () => clearTimeout(timer);
  }, [teamB]);

  const handleSimulate = async () => {
    if (!teamA.trim() || !teamB.trim()) {
      setError('Wybierz obie drużyny do porównania.');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const data = await simulateMatchup({
        team_a_name: teamA.trim(),
        team_b_name: teamB.trim(),
        best_of: bestOf,
        league: league.trim() || undefined,
      });
      setResult(data);
    } catch (err: unknown) {
      setError(err instanceof Error && err.message ? err.message : 'Błąd podczas symulacji starcia.');
    } finally {
      setLoading(false);
    }
  };

  // Run on first render with defaults
  useEffect(() => {
    handleSimulate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="matchup-page">
      <header className="matchup-header">
        <p className="eyebrow">Symulator starć bezpośrednich</p>
        <h1>Matchup Simulator (H2H)</h1>
        <p className="subtitle">
          Zestaw ze sobą dwie dowolne drużyny (nawet z różnych lig lub reprezentacji), wybierz format serii i zobacz predykcję modelu oraz porównanie ratingów.
        </p>
      </header>

      <section className="matchup-controls-card">
        <div className="matchup-inputs-row">
          <div className="team-input-block">
            <label htmlFor="team-a-input">Drużyna A (Niebieska / Gospodarz)</label>
            <input
              id="team-a-input"
              type="text"
              value={teamA}
              onChange={(e) => setTeamA(e.target.value)}
              placeholder="np. T1, Gen.G, Fnatic..."
            />
            {searchingA && <small className="searching-hint">Szukanie w GOL.GG...</small>}
            {candidatesA.length > 0 && (
              <div className="candidates-list">
                {candidatesA.map((name) => (
                  <button
                    key={name}
                    type="button"
                    className="candidate-item"
                    onClick={() => {
                      setTeamA(name);
                      setCandidatesA([]);
                    }}
                  >
                    {name}
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="versus-badge">VS</div>

          <div className="team-input-block">
            <label htmlFor="team-b-input">Drużyna B (Czerwona / Gość)</label>
            <input
              id="team-b-input"
              type="text"
              value={teamB}
              onChange={(e) => setTeamB(e.target.value)}
              placeholder="np. Bilibili Gaming, Cloud9..."
            />
            {searchingB && <small className="searching-hint">Szukanie w GOL.GG...</small>}
            {candidatesB.length > 0 && (
              <div className="candidates-list">
                {candidatesB.map((name) => (
                  <button
                    key={name}
                    type="button"
                    className="candidate-item"
                    onClick={() => {
                      setTeamB(name);
                      setCandidatesB([]);
                    }}
                  >
                    {name}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="matchup-options-row">
          <div className="option-item">
            <span>Format serii:</span>
            <div className="bo-selector">
              {[1, 3, 5, 7].map((b) => (
                <button
                  key={b}
                  type="button"
                  className={bestOf === b ? 'active' : ''}
                  onClick={() => setBestOf(b)}
                >
                  Bo{b}
                </button>
              ))}
            </div>
          </div>

          <div className="option-item">
            <label htmlFor="league-context">Kontekst ligi:</label>
            <input
              id="league-context"
              type="text"
              value={league}
              onChange={(e) => setLeague(e.target.value)}
              placeholder="np. LCK, Worlds, MSI..."
            />
          </div>

          <button
            type="button"
            className={`simulate-btn ${loading ? 'loading' : ''}`}
            onClick={handleSimulate}
            disabled={loading}
          >
            {loading ? '⏳ Symulacja...' : '⚡ Porównaj drużyny'}
          </button>
        </div>

        {error && <div className="matchup-error">{error}</div>}
      </section>

      {result && (
        <section className="matchup-results-section">
          {/* Main probability banner */}
          <div className="probability-hero-card">
            <div className="hero-side left">
              <h2>{result.team_a_name}</h2>
              <span className="series-prob">{(result.series_prob_a * 100).toFixed(1)}%</span>
              <small className="map-prob">Pojedyncza mapa: {(result.map_prob_a * 100).toFixed(1)}%</small>
            </div>

            <div className="hero-center">
              <span className="format-badge">Bo{result.best_of}</span>
              <div className="prob-bar-track">
                <div
                  className="prob-bar-fill-a"
                  style={{ width: `${result.series_prob_a * 100}%` }}
                />
              </div>
              <small className="model-tag">
                {result.model_name} <span className="version">({result.model_version})</span>
              </small>
            </div>

            <div className="hero-side right">
              <h2>{result.team_b_name}</h2>
              <span className="series-prob">{(result.series_prob_b * 100).toFixed(1)}%</span>
              <small className="map-prob">Pojedyncza mapa: {(result.map_prob_b * 100).toFixed(1)}%</small>
            </div>
          </div>

          {/* Model components breakdown */}
          <div className="components-summary-card">
            <h3>Wagi składowe predykcji</h3>
            <div className="components-grid">
              <div className="comp-box">
                <span className="comp-label">Gracze (Consensus 70%)</span>
                <strong className="comp-val">
                  {typeof result.components.player_rating_consensus === 'number'
                    ? `${(result.components.player_rating_consensus * 100).toFixed(1)}%`
                    : '— (brak składu)'}
                </strong>
              </div>
              <div className="comp-box">
                <span className="comp-label">Zespoły (Consensus 20%)</span>
                <strong className="comp-val">
                  {typeof result.components.team_rating_consensus === 'number'
                    ? `${(result.components.team_rating_consensus * 100).toFixed(1)}%`
                    : '— (brak historii)'}
                </strong>
              </div>
              <div className="comp-box">
                <span className="comp-label">Forma W20 (10%)</span>
                <strong className="comp-val">
                  {typeof result.components.w20_probability === 'number'
                    ? `${(result.components.w20_probability * 100).toFixed(1)}%`
                    : '— (brak W20)'}
                </strong>
              </div>
            </div>
          </div>

          {/* Detailed Team & Player Rosters */}
          <div className="rosters-comparison-grid">
            <div className="roster-panel">
              <h3>Skład {result.team_a_name}</h3>
              {result.roster_a?.players?.length ? (
                <ul className="roster-list">
                  {result.roster_a.players.map((p, idx) => (
                    <li key={idx} className="player-row">
                      <span className="role-tag">{p.role || '—'}</span>
                      <strong className="player-name">{p.player_name || 'Nieznany'}</strong>
                      <span className="rating-tag">
                        Glicko {p.glicko_rating ? Math.round(p.glicko_rating) : '—'}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="empty-hint">Brak zapisanego rosteru w bazie GOL.GG</p>
              )}
            </div>

            <div className="roster-panel">
              <h3>Skład {result.team_b_name}</h3>
              {result.roster_b?.players?.length ? (
                <ul className="roster-list">
                  {result.roster_b.players.map((p, idx) => (
                    <li key={idx} className="player-row">
                      <span className="role-tag">{p.role || '—'}</span>
                      <strong className="player-name">{p.player_name || 'Nieznany'}</strong>
                      <span className="rating-tag">
                        Glicko {p.glicko_rating ? Math.round(p.glicko_rating) : '—'}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="empty-hint">Brak zapisanego rosteru w bazie GOL.GG</p>
              )}
            </div>
          </div>
        </section>
      )}
    </div>
  );
}
