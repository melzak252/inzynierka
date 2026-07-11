import { useEffect, useMemo, useState } from 'react';
import {
  blockTeamAlias,
  createTeamAlias,
  searchGolggTeams,
  unblockTeamAlias,
} from '../api/client';
import type {
  GolggMatchCandidate,
  MappingCheckResponse,
  UnmappedMatchItem,
  UnmappedMatchesResponse,
} from '../types';
import './ManualMapping.css';

const API_BASE = '/api';

type StatusFilter = 'upcoming' | 'expired' | 'finished';
type AliasSide = 'a' | 'b';

const STATUS_LABELS: Record<StatusFilter, string> = {
  upcoming: 'Nadchodzące',
  expired: 'Wygasłe',
  finished: 'Zakończone',
};

async function fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, options);
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || `${response.status} ${response.statusText}`);
  }
  return response.json();
}

const formatDateTime = (iso: string | null) => {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('pl-PL', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
};

const formatDate = (iso: string | null) => {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString('pl-PL', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  });
};

export default function ManualMapping() {
  const [unmappedMatches, setUnmappedMatches] = useState<UnmappedMatchItem[]>([]);
  const [selectedMatch, setSelectedMatch] = useState<UnmappedMatchItem | null>(null);
  const [candidates, setCandidates] = useState<GolggMatchCandidate[]>([]);
  const [loading, setLoading] = useState(false);
  const [candidateLoading, setCandidateLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('upcoming');
  const [searchQuery, setSearchQuery] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const [aliasSide, setAliasSide] = useState<AliasSide>('a');
  const [aliasQuery, setAliasQuery] = useState('');
  const [aliasResults, setAliasResults] = useState<string[]>([]);
  const [selectedGolggTeam, setSelectedGolggTeam] = useState('');
  const [aliasSaving, setAliasSaving] = useState(false);

  const [manualId, setManualId] = useState('');
  const [checkResult, setCheckResult] = useState<MappingCheckResponse | null>(null);
  const [checking, setChecking] = useState(false);
  const [mappingMatch, setMappingMatch] = useState(false);

  const rawAliasName = useMemo(() => {
    if (!selectedMatch) return '';
    return aliasSide === 'a' ? selectedMatch.team_a_name : selectedMatch.team_b_name;
  }, [aliasSide, selectedMatch]);

  const filteredMatches = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return unmappedMatches;
    return unmappedMatches.filter((m) => (
      `${m.canonical_match_id} ${m.team_a_name} ${m.team_b_name} ${m.league || ''} ${m.bookmakers?.join(' ') || ''}`
        .toLowerCase()
        .includes(q)
    ));
  }, [searchQuery, unmappedMatches]);

  const fetchUnmapped = async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ status: statusFilter, limit: '250' });
      const data = await fetchJson<UnmappedMatchesResponse>(`${API_BASE}/matches/unmapped?${params}`);
      setUnmappedMatches(data.matches);
      if (selectedMatch && !data.matches.some((m) => m.canonical_match_id === selectedMatch.canonical_match_id)) {
        setSelectedMatch(null);
        setCandidates([]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Nie udało się pobrać listy meczów');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchUnmapped();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter]);

  useEffect(() => {
    if (!selectedMatch) return;
    const initialQuery = aliasSide === 'a' ? selectedMatch.team_a_name : selectedMatch.team_b_name;
    setAliasQuery(initialQuery || '');
    setSelectedGolggTeam('');
    setAliasResults([]);
  }, [aliasSide, selectedMatch]);

  useEffect(() => {
    const q = aliasQuery.trim();
    if (!q) {
      setAliasResults([]);
      return;
    }
    const handle = window.setTimeout(async () => {
      try {
        const data = await searchGolggTeams(q, 20);
        setAliasResults(data.teams);
      } catch {
        setAliasResults([]);
      }
    }, 250);
    return () => window.clearTimeout(handle);
  }, [aliasQuery]);

  const handleSelectMatch = async (match: UnmappedMatchItem) => {
    setSelectedMatch(match);
    setAliasSide('a');
    setCandidates([]);
    setManualId('');
    setCheckResult(null);
    setError(null);
    setSuccess(null);
    setCandidateLoading(true);
    try {
      const data = await fetchJson<{ candidates: GolggMatchCandidate[] }>(
        `${API_BASE}/matches/${match.canonical_match_id}/mapping-candidates`
      );
      setCandidates(data.candidates);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Nie udało się pobrać kandydatów GOL.GG');
    } finally {
      setCandidateLoading(false);
    }
  };

  const handleSaveAlias = async () => {
    if (!rawAliasName || !selectedGolggTeam) return;
    setAliasSaving(true);
    setError(null);
    setSuccess(null);
    try {
      await createTeamAlias({ raw_name: rawAliasName, golgg_team_name: selectedGolggTeam });
      setSuccess(`Dodano alias: ${rawAliasName} → ${selectedGolggTeam}`);
      await fetchUnmapped();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Nie udało się zapisać aliasu');
    } finally {
      setAliasSaving(false);
    }
  };

  const handleBlockAlias = async () => {
    if (!rawAliasName) return;
    setAliasSaving(true);
    setError(null);
    setSuccess(null);
    try {
      await blockTeamAlias(rawAliasName);
      setSuccess(`Zablokowano automapowanie dla: ${rawAliasName}`);
      await fetchUnmapped();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Nie udało się zablokować aliasu');
    } finally {
      setAliasSaving(false);
    }
  };

  const handleUnblockAlias = async () => {
    if (!rawAliasName) return;
    setAliasSaving(true);
    setError(null);
    setSuccess(null);
    try {
      await unblockTeamAlias(rawAliasName);
      setSuccess(`Odblokowano automapowanie dla: ${rawAliasName}`);
      await fetchUnmapped();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Nie udało się odblokować aliasu');
    } finally {
      setAliasSaving(false);
    }
  };

  const handleCheckId = async () => {
    if (!manualId.trim()) return;
    setChecking(true);
    setError(null);
    setCheckResult(null);
    try {
      const data = await fetchJson<MappingCheckResponse>(`${API_BASE}/matches/mapping-check/${manualId.trim()}`);
      setCheckResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Nie udało się sprawdzić ID GOL.GG');
    } finally {
      setChecking(false);
    }
  };

  const handleMapMatch = async (golggMatchId: string | number) => {
    if (!selectedMatch) return;
    setMappingMatch(true);
    setError(null);
    setSuccess(null);
    try {
      await fetchJson<{ ok: boolean }>(`${API_BASE}/matches/map`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          canonical_match_id: selectedMatch.canonical_match_id,
          golgg_match_id: String(golggMatchId),
        }),
      });
      setSuccess(`Zmapowano mecz #${selectedMatch.canonical_match_id} → GOL.GG #${golggMatchId}`);
      setSelectedMatch(null);
      setCandidates([]);
      setManualId('');
      setCheckResult(null);
      await fetchUnmapped();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Nie udało się zmapować meczu');
    } finally {
      setMappingMatch(false);
    }
  };

  return (
    <div className="manual-mapping-page">
      <div className="mapping-page-header">
        <div>
          <h1>Mapowanie</h1>
          <p className="mapping-subtitle">
            Najpierw napraw mapowania drużyn aliasami. Mapowanie meczu do GOL.GG zostaw jako awaryjny krok dla wyników historycznych.
          </p>
        </div>
        <button className="secondary-btn" onClick={fetchUnmapped} disabled={loading}>
          {loading ? 'Odświeżanie…' : 'Odśwież'}
        </button>
      </div>

      {(error || success) && (
        <div className={`mapping-alert ${error ? 'error' : 'success'}`}>
          {error || success}
        </div>
      )}

      <div className="mapping-toolbar">
        <div className="status-tabs" role="tablist" aria-label="Status meczów">
          {(Object.keys(STATUS_LABELS) as StatusFilter[]).map((status) => (
            <button
              key={status}
              className={statusFilter === status ? 'active' : ''}
              onClick={() => setStatusFilter(status)}
              type="button"
            >
              {STATUS_LABELS[status]}
            </button>
          ))}
        </div>
        <input
          className="mapping-search"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Szukaj po drużynie, lidze, ID, bukmacherze…"
        />
      </div>

      <div className="mapping-container">
        <section className="unmapped-list-section">
          <div className="section-header">
            <div>
              <h2>Niezmapowane mecze</h2>
              <span>{filteredMatches.length} / {unmappedMatches.length} dla statusu: {STATUS_LABELS[statusFilter]}</span>
            </div>
          </div>

          {loading ? (
            <div className="empty-state">Ładowanie…</div>
          ) : filteredMatches.length === 0 ? (
            <div className="empty-state">Brak meczów dla wybranego filtra.</div>
          ) : (
            <div className="scroll-list">
              {filteredMatches.map((m) => (
                <button
                  key={m.canonical_match_id}
                  className={`match-item ${selectedMatch?.canonical_match_id === m.canonical_match_id ? 'selected' : ''}`}
                  onClick={() => handleSelectMatch(m)}
                  type="button"
                >
                  <div className="match-row-top">
                    <span className="match-id">#{m.canonical_match_id}</span>
                    <span className="match-time">{formatDate(m.start_time_normalized)}</span>
                  </div>
                  <div className="match-teams">{m.team_a_name} vs {m.team_b_name}</div>
                  <div className="match-league">{m.league || 'Nieznana liga'}</div>
                  {m.bookmakers && m.bookmakers.length > 0 && (
                    <div className="match-sources">Bukmacherzy: {m.bookmakers.join(', ')}</div>
                  )}
                </button>
              ))}
            </div>
          )}
        </section>

        <section className="mapping-workspace">
          {!selectedMatch ? (
            <div className="empty-state">
              Wybierz mecz z listy. Po prawej dostaniesz szybkie mapowanie aliasów drużyn i opcjonalne mapowanie meczu do GOL.GG.
            </div>
          ) : (
            <>
              <div className="selected-match-info">
                <div>
                  <span className="match-id">#{selectedMatch.canonical_match_id}</span>
                  <h2>{selectedMatch.team_a_name} vs {selectedMatch.team_b_name}</h2>
                  <p>{formatDateTime(selectedMatch.start_time_normalized)} · {selectedMatch.league || 'Nieznana liga'}</p>
                </div>
                <a href={`/matches/${selectedMatch.canonical_match_id}`} className="detail-link">
                  Szczegóły meczu →
                </a>
              </div>

              <div className="mapping-card priority-card">
                <div className="card-title-row">
                  <div>
                    <h3>1. Alias drużyny</h3>
                    <p>To jest główny workflow dla obecnych predykcji — mapuje nazwę bukmachera na nazwę GOL.GG.</p>
                  </div>
                </div>

                <div className="side-picker">
                  <button className={aliasSide === 'a' ? 'active' : ''} onClick={() => setAliasSide('a')} type="button">
                    {selectedMatch.team_a_name}
                  </button>
                  <button className={aliasSide === 'b' ? 'active' : ''} onClick={() => setAliasSide('b')} type="button">
                    {selectedMatch.team_b_name}
                  </button>
                </div>

                <label className="field-label">
                  Surowa nazwa
                  <input value={rawAliasName} readOnly />
                </label>

                <label className="field-label">
                  Szukaj drużyny GOL.GG
                  <input
                    value={aliasQuery}
                    onChange={(e) => {
                      setAliasQuery(e.target.value);
                      setSelectedGolggTeam('');
                    }}
                    placeholder="Wpisz nazwę z GOL.GG…"
                  />
                </label>

                <div className="alias-results">
                  {aliasResults.length === 0 ? (
                    <span>Brak wyników — zmień frazę albo wpisz dokładniejszą nazwę.</span>
                  ) : aliasResults.map((team) => (
                    <button
                      key={team}
                      className={selectedGolggTeam === team ? 'active' : ''}
                      onClick={() => setSelectedGolggTeam(team)}
                      type="button"
                    >
                      {team}
                    </button>
                  ))}
                </div>

                <div className="action-row">
                  <button
                    className="primary-btn"
                    onClick={handleSaveAlias}
                    disabled={!selectedGolggTeam || aliasSaving}
                    type="button"
                  >
                    {aliasSaving ? 'Zapisywanie…' : `Zapisz alias${selectedGolggTeam ? ` → ${selectedGolggTeam}` : ''}`}
                  </button>
                  <button className="danger-btn" onClick={handleBlockAlias} disabled={aliasSaving} type="button">
                    Oznacz jako brak mapowania
                  </button>
                  <button className="secondary-btn" onClick={handleUnblockAlias} disabled={aliasSaving} type="button">
                    Odblokuj
                  </button>
                </div>
              </div>

              <div className="mapping-card">
                <h3>2. Opcjonalnie: mapowanie meczu do GOL.GG</h3>
                <p>Używaj głównie dla wygasłych/zakończonych meczów, gdy chcesz przypiąć konkretny wynik GOL.GG.</p>

                <div className="manual-id-entry">
                  <div className="input-group">
                    <input
                      type="number"
                      placeholder="GOL.GG Match ID"
                      value={manualId}
                      onChange={(e) => {
                        setManualId(e.target.value);
                        setCheckResult(null);
                      }}
                    />
                    <button onClick={handleCheckId} disabled={!manualId || checking} type="button">
                      {checking ? 'Sprawdzanie…' : 'Sprawdź ID'}
                    </button>
                  </div>

                  {checkResult && (
                    <div className={`check-result ${checkResult.is_mapped ? 'warning' : 'success'}`}>
                      <div>
                        {checkResult.is_mapped ? (
                          <>
                            <strong>To ID jest już przypisane</strong><br />
                            {checkResult.team_a} vs {checkResult.team_b} ({formatDate(checkResult.start_time)})
                          </>
                        ) : (
                          <><strong>ID jest wolne.</strong> Możesz je przypisać do wybranego meczu.</>
                        )}
                      </div>
                      <button className="map-manual-btn" onClick={() => handleMapMatch(manualId)} disabled={mappingMatch} type="button">
                        Mapuj to ID
                      </button>
                    </div>
                  )}
                </div>

                <div className="candidates-list">
                  <h4>Sugerowani kandydaci ±3 dni</h4>
                  {candidateLoading ? (
                    <div className="empty-state compact">Ładowanie kandydatów…</div>
                  ) : candidates.length === 0 ? (
                    <div className="empty-state compact">Brak kandydatów w oknie czasowym.</div>
                  ) : (
                    candidates.map((c) => (
                      <div key={c.match_id} className="candidate-item">
                        <div className="candidate-info">
                          <div className="candidate-date">{formatDate(c.date)} · GOL.GG #{c.match_id}</div>
                          <div className="candidate-teams">{c.team1_name} vs {c.team2_name}</div>
                          <div className="candidate-result">
                            {c.team1_win === null && c.team2_win === null
                              ? 'Brak wyniku'
                              : c.team1_win
                                ? 'Wygrała drużyna 1'
                                : 'Wygrała drużyna 2'}
                          </div>
                        </div>
                        <button onClick={() => handleMapMatch(c.match_id)} disabled={mappingMatch} type="button">
                          Mapuj
                        </button>
                      </div>
                    ))
                  )}
                </div>
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  );
}
