import type {
  Signal,
  Plug,
  Output,
  HealthStatus,
  SystemStatus,
  RiskSummary,
  SignalStats,
  SystemConfig,
  PlugPerformance,
} from '../types';

const API_BASE = '/api/v1';

async function fetchAPI<T>(
  endpoint: string,
  options?: RequestInit
): Promise<T> {
  const response = await fetch(`${API_BASE}${endpoint}`, {
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
    ...options,
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
    throw new Error(error.detail || `API Error: ${response.status}`);
  }

  return response.json();
}

// Health & Status
export async function getHealth(): Promise<HealthStatus> {
  return fetchAPI<HealthStatus>('/health');
}

export async function getStatus(): Promise<SystemStatus> {
  return fetchAPI<SystemStatus>('/status');
}

// Signals
export async function generateSignal(symbol: string): Promise<Signal> {
  return fetchAPI<Signal>('/signals/generate', {
    method: 'POST',
    body: JSON.stringify({ symbol }),
  });
}

export async function getSignals(params?: {
  symbol?: string;
  action?: string;
  min_confidence?: number;
  hours?: number;
  limit?: number;
}): Promise<Signal[]> {
  const searchParams = new URLSearchParams();
  if (params?.symbol) searchParams.set('symbol', params.symbol);
  if (params?.action) searchParams.set('action', params.action);
  if (params?.min_confidence) searchParams.set('min_confidence', params.min_confidence.toString());
  if (params?.hours) searchParams.set('hours', params.hours.toString());
  if (params?.limit) searchParams.set('limit', params.limit.toString());

  const query = searchParams.toString();
  return fetchAPI<Signal[]>(`/signals${query ? `?${query}` : ''}`);
}

export async function getSignal(signalId: string): Promise<Signal> {
  return fetchAPI<Signal>(`/signals/${signalId}`);
}

export async function getSignalStats(symbol: string, hours = 24): Promise<SignalStats> {
  return fetchAPI<SignalStats>(`/signals/stats/${symbol}?hours=${hours}`);
}

// Plugs
export async function getPlugs(): Promise<Record<string, Plug>> {
  return fetchAPI<Record<string, Plug>>('/plugs');
}

export async function getPlug(plugId: string): Promise<Plug> {
  return fetchAPI<Plug>(`/plugs/${plugId}`);
}

export async function updatePlugWeight(plugId: string, weight: number): Promise<void> {
  await fetchAPI(`/plugs/${plugId}/weight`, {
    method: 'PUT',
    body: JSON.stringify({ weight }),
  });
}

export async function updatePlugStatus(plugId: string, enabled: boolean): Promise<void> {
  await fetchAPI(`/plugs/${plugId}/status`, {
    method: 'PUT',
    body: JSON.stringify({ enabled }),
  });
}

export async function getPlugPerformance(): Promise<Record<string, PlugPerformance>> {
  return fetchAPI<Record<string, PlugPerformance>>('/plugs/performance');
}

export async function getPlugRanking(): Promise<Array<{ plug_id: string; score: number }>> {
  return fetchAPI('/plugs/ranking');
}

// Configuration
export async function getConfig(): Promise<SystemConfig> {
  return fetchAPI<SystemConfig>('/config');
}

export async function getWeights(): Promise<Record<string, number>> {
  return fetchAPI<Record<string, number>>('/config/weights');
}

export async function resetWeights(): Promise<void> {
  await fetchAPI('/config/weights/reset', { method: 'POST' });
}

// Risk
export async function getRiskSummary(): Promise<RiskSummary> {
  return fetchAPI<RiskSummary>('/risk/summary');
}

export async function resetRiskSession(): Promise<void> {
  await fetchAPI('/risk/session/reset', { method: 'POST' });
}

// Outputs
export async function getOutputs(): Promise<Record<string, Output>> {
  return fetchAPI<Record<string, Output>>('/outputs');
}

export async function enableOutput(outputId: string): Promise<void> {
  await fetchAPI(`/outputs/${outputId}/enable`, { method: 'PUT' });
}

export async function disableOutput(outputId: string): Promise<void> {
  await fetchAPI(`/outputs/${outputId}/disable`, { method: 'PUT' });
}
