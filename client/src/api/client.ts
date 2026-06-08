import type {
  MatchBoardResponse,
  MatchDetailResponse,
  MatchResultsResponse,
  SystemStatusResponse,
  BookmakerStatus,
  SchedulerTask,
  SchedulerJob,
  SchedulerRun,
  SchedulerCommand,
  SchedulerTriggerResponse,
  MatchMovementResponse,
  HorizonAccuracyResponse,
  PredictionHistoryPoint,
} from '../types';

const API_BASE = '/api';

// ─── Matches ────────────────────────────────────────────────

export async function fetchMatches(
  minBooks: number = 1,
  daysAhead: number = 14
): Promise<MatchBoardResponse> {
  const params = new URLSearchParams({
    min_books: minBooks.toString(),
    days_ahead: daysAhead.toString(),
  });
  const response = await fetch(`${API_BASE}/matches?${params}`);
  if (!response.ok) throw new Error(`Failed to fetch matches: ${response.statusText}`);
  return response.json();
}

export async function fetchMatchDetail(matchId: number): Promise<MatchDetailResponse> {
  const response = await fetch(`${API_BASE}/matches/${matchId}`);
  if (!response.ok) throw new Error(`Failed to fetch match ${matchId}: ${response.statusText}`);
  return response.json();
}

export async function updateMatchBestOf(matchId: number, bestOf: number): Promise<{ best_of: number }> {
  const response = await fetch(`${API_BASE}/matches/${matchId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ best_of: bestOf }),
  });
  if (!response.ok) throw new Error(`Failed to update best_of: ${response.statusText}`);
  return response.json();
}

export async function fetchMatchResults(daysBack: number = 30): Promise<MatchResultsResponse> {
  const params = new URLSearchParams({ days_back: daysBack.toString() });
  const response = await fetch(`${API_BASE}/matches/results?${params}`);
  if (!response.ok) throw new Error(`Failed to fetch match results: ${response.statusText}`);
  return response.json();
}

export async function fetchHealth(): Promise<{ status: string; version: string }> {
  const response = await fetch(`${API_BASE}/health`);
  if (!response.ok) throw new Error(`Failed to fetch health: ${response.statusText}`);
  return response.json();
}

// ─── System ─────────────────────────────────────────────────

export async function fetchSystemStatus(): Promise<SystemStatusResponse> {
  const response = await fetch(`${API_BASE}/system/status`);
  if (!response.ok) throw new Error(`Failed to fetch system status: ${response.statusText}`);
  return response.json();
}

export async function fetchBookmakers(): Promise<BookmakerStatus[]> {
  const response = await fetch(`${API_BASE}/bookmakers`);
  if (!response.ok) throw new Error(`Failed to fetch bookmakers: ${response.statusText}`);
  return response.json();
}

export async function triggerLightCycle(): Promise<{ status: string; message: string }> {
  const response = await fetch(`${API_BASE}/automation/light-cycle`, { method: 'POST' });
  if (!response.ok) throw new Error(`Failed to trigger light cycle: ${response.statusText}`);
  return response.json();
}

export async function triggerBackup(): Promise<{ status: string; message: string }> {
  const response = await fetch(`${API_BASE}/automation/backup`, { method: 'POST' });
  if (!response.ok) throw new Error(`Failed to trigger backup: ${response.statusText}`);
  return response.json();
}

// ─── Scheduler ──────────────────────────────────────────────

export async function fetchSchedulerTasks(): Promise<SchedulerTask[]> {
  const response = await fetch(`${API_BASE}/scheduler/tasks`);
  if (!response.ok) throw new Error(`Failed to fetch scheduler tasks: ${response.statusText}`);
  return response.json();
}

export async function fetchSchedulerJobs(): Promise<SchedulerJob[]> {
  const response = await fetch(`${API_BASE}/scheduler/jobs`);
  if (!response.ok) throw new Error(`Failed to fetch scheduler jobs: ${response.statusText}`);
  return response.json();
}

export async function fetchSchedulerRuns(): Promise<SchedulerRun[]> {
  const response = await fetch(`${API_BASE}/scheduler/runs`);
  if (!response.ok) throw new Error(`Failed to fetch scheduler runs: ${response.statusText}`);
  return response.json();
}

export async function fetchSchedulerRunCommands(runId: number): Promise<SchedulerCommand[]> {
  const response = await fetch(`${API_BASE}/scheduler/runs/${runId}/commands`);
  if (!response.ok) throw new Error(`Failed to fetch run commands: ${response.statusText}`);
  return response.json();
}

export async function triggerSchedulerTask(taskId: string): Promise<SchedulerTriggerResponse> {
  const response = await fetch(`${API_BASE}/scheduler/trigger/${taskId}`, { method: 'POST' });
  if (!response.ok) throw new Error(`Failed to trigger task: ${response.statusText}`);
  return response.json();
}

// ─── Predict ─────────────────────────────────────────────────

export interface PredictResult {
  status: string;
  message: string;
  prob_a: number | null;
  prob_b: number | null;
  hybrid_prob_a: number | null;
  hybrid_prob_b: number | null;
  model_name: string | null;
  model_version: string | null;
  diagnostics: Record<string, unknown> | null;
}

export async function predictMatch(matchId: number): Promise<PredictResult> {
  const response = await fetch(`${API_BASE}/matches/${matchId}/predict`, { method: 'POST' });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || `Failed to predict match ${matchId}: ${response.statusText}`);
  }
  return response.json();
}

// ─── Prediction History ──────────────────────────────────────

export async function fetchPredictionHistory(matchId: number): Promise<PredictionHistoryPoint[]> {
  const response = await fetch(`${API_BASE}/matches/${matchId}/prediction-history`);
  if (!response.ok) throw new Error(`Failed to fetch prediction history: ${response.statusText}`);
  return response.json();
}

// ─── Timing Analysis ────────────────────────────────────────

export async function fetchMatchMovement(matchId: number): Promise<MatchMovementResponse> {
  const response = await fetch(`${API_BASE}/timing/match/${matchId}/movement`);
  if (!response.ok) throw new Error(`Failed to fetch match movement: ${response.statusText}`);
  return response.json();
}

export async function fetchHorizonAccuracy(
  daysBack: number = 90,
  minMatchesPerBin: number = 10
): Promise<HorizonAccuracyResponse> {
  const params = new URLSearchParams({
    days_back: daysBack.toString(),
    min_matches_per_bin: minMatchesPerBin.toString(),
  });
  const response = await fetch(`${API_BASE}/timing/horizon-accuracy?${params}`);
  if (!response.ok) throw new Error(`Failed to fetch horizon accuracy: ${response.statusText}`);
  return response.json();
}
