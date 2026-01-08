-- Aegis-1 Database Initialization Script
-- TimescaleDB Schema

-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ===================
-- Signals Table (Hypertable)
-- ===================
CREATE TABLE IF NOT EXISTS signals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    action VARCHAR(10) NOT NULL CHECK (action IN ('BUY', 'SELL', 'HOLD')),
    symbol VARCHAR(20) NOT NULL,
    confidence DECIMAL(5,4) NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    position_size DECIMAL(20,8) NOT NULL DEFAULT 0,
    reasoning TEXT,
    risk_score DECIMAL(5,4) NOT NULL CHECK (risk_score >= 0 AND risk_score <= 1),
    expiry TIMESTAMPTZ,
    origin VARCHAR(50) NOT NULL,
    plug_contributions JSONB DEFAULT '{}',
    risk_decision VARCHAR(10) NOT NULL DEFAULT 'EXECUTE' CHECK (risk_decision IN ('EXECUTE', 'ABORT')),
    var_estimate DECIMAL(20,8),
    max_drawdown DECIMAL(20,8),
    market_regime VARCHAR(20),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Convert to hypertable for time-series optimization
SELECT create_hypertable('signals', 'timestamp', if_not_exists => TRUE);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals (symbol, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_signals_action ON signals (action, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_signals_confidence ON signals (confidence DESC, timestamp DESC);

-- ===================
-- Trades Table
-- ===================
CREATE TABLE IF NOT EXISTS trades (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    signal_id UUID REFERENCES signals(id),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    symbol VARCHAR(20) NOT NULL,
    action VARCHAR(10) NOT NULL CHECK (action IN ('BUY', 'SELL')),
    quantity DECIMAL(20,8) NOT NULL,
    price DECIMAL(20,8) NOT NULL,
    total_value DECIMAL(20,8) NOT NULL,
    exchange VARCHAR(20) NOT NULL,
    order_id VARCHAR(100),
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'FILLED', 'PARTIAL', 'CANCELLED', 'REJECTED')),
    fill_price DECIMAL(20,8),
    fill_quantity DECIMAL(20,8),
    fees DECIMAL(20,8) DEFAULT 0,
    slippage DECIMAL(20,8),
    pnl DECIMAL(20,8),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Convert to hypertable
SELECT create_hypertable('trades', 'timestamp', if_not_exists => TRUE);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_trades_signal ON trades (signal_id);
CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades (symbol, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_trades_status ON trades (status, timestamp DESC);

-- ===================
-- Audit Snapshots Table
-- ===================
CREATE TABLE IF NOT EXISTS audit_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    signal_id UUID REFERENCES signals(id),
    trade_id UUID REFERENCES trades(id),
    plug_states JSONB NOT NULL DEFAULT '{}',
    market_data_snapshot JSONB NOT NULL DEFAULT '{}',
    orchestrator_weights JSONB NOT NULL DEFAULT '{}',
    reasoning_path TEXT,
    blackboard_state JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Convert to hypertable
SELECT create_hypertable('audit_snapshots', 'timestamp', if_not_exists => TRUE);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_audit_signal ON audit_snapshots (signal_id);
CREATE INDEX IF NOT EXISTS idx_audit_trade ON audit_snapshots (trade_id);

-- ===================
-- Market Data Table (for historical analysis)
-- ===================
CREATE TABLE IF NOT EXISTS market_data (
    timestamp TIMESTAMPTZ NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    exchange VARCHAR(20) NOT NULL,
    price DECIMAL(20,8) NOT NULL,
    volume DECIMAL(20,8) NOT NULL,
    bid DECIMAL(20,8),
    ask DECIMAL(20,8),
    open DECIMAL(20,8),
    high DECIMAL(20,8),
    low DECIMAL(20,8),
    close DECIMAL(20,8),
    timeframe VARCHAR(10) DEFAULT '1m',
    PRIMARY KEY (timestamp, symbol, exchange, timeframe)
);

-- Convert to hypertable
SELECT create_hypertable('market_data', 'timestamp', if_not_exists => TRUE);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_market_data_symbol ON market_data (symbol, timestamp DESC);

-- ===================
-- Plug Performance Ledger
-- ===================
CREATE TABLE IF NOT EXISTS plug_performance (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    plug_id VARCHAR(50) NOT NULL,
    signal_id UUID REFERENCES signals(id),
    predicted_direction DECIMAL(5,4) NOT NULL,
    actual_direction DECIMAL(5,4),
    accuracy DECIMAL(5,4),
    contribution_weight DECIMAL(5,4) NOT NULL DEFAULT 1.0,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Convert to hypertable
SELECT create_hypertable('plug_performance', 'timestamp', if_not_exists => TRUE);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_plug_perf_plug ON plug_performance (plug_id, timestamp DESC);

-- ===================
-- System Configuration Table
-- ===================
CREATE TABLE IF NOT EXISTS system_config (
    key VARCHAR(100) PRIMARY KEY,
    value JSONB NOT NULL,
    description TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by VARCHAR(100)
);

-- Insert default configurations
INSERT INTO system_config (key, value, description) VALUES
    ('plug_weights', '{"news_sentry": 1.0, "gemini_vector": 1.0, "quant_engine": 1.0, "risk_analyst": 1.0}', 'Default plug weights'),
    ('risk_limits', '{"max_drawdown": 5.0, "kill_switch_loss": 2.0, "max_position_size": 10.0}', 'Risk management limits'),
    ('output_config', '{"webhook_enabled": true, "email_enabled": true, "database_enabled": true, "mq_enabled": true}', 'Output plug configuration')
ON CONFLICT (key) DO NOTHING;

-- ===================
-- Alert History Table
-- ===================
CREATE TABLE IF NOT EXISTS alert_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    alert_type VARCHAR(50) NOT NULL,
    severity VARCHAR(20) NOT NULL CHECK (severity IN ('INFO', 'WARNING', 'ERROR', 'CRITICAL')),
    message TEXT NOT NULL,
    signal_id UUID REFERENCES signals(id),
    acknowledged BOOLEAN DEFAULT FALSE,
    acknowledged_by VARCHAR(100),
    acknowledged_at TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}'
);

-- Convert to hypertable
SELECT create_hypertable('alert_history', 'timestamp', if_not_exists => TRUE);

-- ===================
-- Data Retention Policies
-- ===================
-- Keep signals for 1 year
SELECT add_retention_policy('signals', INTERVAL '1 year', if_not_exists => TRUE);

-- Keep trades for 5 years
SELECT add_retention_policy('trades', INTERVAL '5 years', if_not_exists => TRUE);

-- Keep audit snapshots for 2 years
SELECT add_retention_policy('audit_snapshots', INTERVAL '2 years', if_not_exists => TRUE);

-- Keep market data for 1 year
SELECT add_retention_policy('market_data', INTERVAL '1 year', if_not_exists => TRUE);

-- Keep plug performance for 1 year
SELECT add_retention_policy('plug_performance', INTERVAL '1 year', if_not_exists => TRUE);

-- Keep alert history for 6 months
SELECT add_retention_policy('alert_history', INTERVAL '6 months', if_not_exists => TRUE);

-- ===================
-- Continuous Aggregates for Performance Metrics
-- ===================
CREATE MATERIALIZED VIEW IF NOT EXISTS hourly_signal_stats
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', timestamp) AS bucket,
    symbol,
    action,
    COUNT(*) AS signal_count,
    AVG(confidence) AS avg_confidence,
    AVG(risk_score) AS avg_risk_score,
    SUM(CASE WHEN risk_decision = 'EXECUTE' THEN 1 ELSE 0 END) AS executed_count,
    SUM(CASE WHEN risk_decision = 'ABORT' THEN 1 ELSE 0 END) AS aborted_count
FROM signals
GROUP BY bucket, symbol, action
WITH NO DATA;

-- Refresh policy for continuous aggregate
SELECT add_continuous_aggregate_policy('hourly_signal_stats',
    start_offset => INTERVAL '3 hours',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE
);
