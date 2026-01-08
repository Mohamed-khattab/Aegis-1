// Signal Types
export type SignalAction = 'BUY' | 'SELL' | 'HOLD';
export type RiskDecision = 'EXECUTE' | 'ABORT';

export interface Signal {
  id: string;
  timestamp: string;
  action: SignalAction;
  symbol: string;
  confidence: number;
  position_size: number;
  reasoning: string;
  risk_score: number;
  risk_decision: RiskDecision;
  plug_contributions: Record<string, PlugContribution>;
  is_critical?: boolean;
  is_actionable?: boolean;
}

export interface PlugContribution {
  direction: number;
  confidence: number;
}

// Plug Types
export type PlugStatus = 'ACTIVE' | 'INACTIVE' | 'ISOLATED' | 'DEGRADED';

export interface PlugMetrics {
  total_signals: number;
  accuracy: number;
  avg_confidence: number;
  avg_latency_ms: number;
  isolation_count: number;
}

export interface Plug {
  plug_id: string;
  status: PlugStatus;
  weight: number;
  metrics: PlugMetrics;
  last_error?: string;
}

// Output Types
export type OutputStatus = 'ACTIVE' | 'INACTIVE' | 'DEGRADED' | 'ERROR';

export interface OutputMetrics {
  signals_sent: number;
  signals_failed: number;
  success_rate: number;
  avg_delivery_time_ms: number;
  retry_count: number;
}

export interface Output {
  output_id: string;
  status: OutputStatus;
  enabled: boolean;
  min_priority: string;
  metrics: OutputMetrics;
}

// System Health
export interface HealthStatus {
  status: 'healthy' | 'degraded' | 'unhealthy';
  timestamp: string;
  components: Record<string, boolean>;
}

export interface SystemStatus {
  initialized: boolean;
  running: boolean;
  plugs: Record<string, Plug>;
  weights: Record<string, number>;
  blackboard: BlackboardSummary;
  performance: Record<string, PlugPerformance>;
}

export interface BlackboardSummary {
  signal_count: number;
  plugs: string[];
  weights: Record<string, number>;
  last_update: string;
  market_data_symbols: string[];
}

export interface PlugPerformance {
  plug_id: string;
  total_predictions: number;
  correct_predictions: number;
  overall_accuracy: number;
  rolling_accuracy: number;
  rolling_confidence: number;
  correlation: number;
  current_weight: number;
  last_updated: string;
}

// Risk Types
export interface RiskSummary {
  portfolio_value: number;
  peak_value: number;
  current_drawdown: number;
  max_drawdown_limit: number;
  session_pnl: number;
  session_pnl_percent: number;
  kill_switch_limit: number;
  positions: Record<string, Position>;
  trade_count: number;
}

export interface Position {
  quantity: number;
  value: number;
}

// Signal Stats
export interface SignalStats {
  total_signals: number;
  avg_confidence: number;
  avg_risk_score: number;
  buy_count: number;
  sell_count: number;
  hold_count: number;
  aborted_count: number;
}

// WebSocket Message Types
export interface WSMessage {
  type: string;
  data: unknown;
  timestamp?: string;
}

export interface WSSignalMessage {
  type: 'signal';
  data: Signal;
}

export interface WSHealthMessage {
  type: 'health';
  data: Record<string, boolean>;
}

export interface WSPlugStatusMessage {
  type: 'plug_status';
  data: Record<string, Plug>;
}

// Config Types
export interface SystemConfig {
  max_drawdown_percent: number;
  kill_switch_loss_percent: number;
  pinecone_similarity_threshold: number;
  max_consensus_latency_ms: number;
  max_e2e_latency_ms: number;
  volatility_threshold_multiplier: number;
}
