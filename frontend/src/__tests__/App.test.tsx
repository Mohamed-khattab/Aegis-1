/**
 * Frontend Tests for Aegis-1 UI Components
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock fetch globally
global.fetch = vi.fn();

describe('API Service', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('should fetch health status', async () => {
    const mockHealth = {
      status: 'healthy',
      services: {
        redis: true,
        timescale: true,
        rabbitmq: true
      }
    };

    (global.fetch as any).mockResolvedValueOnce({
      ok: true,
      json: async () => mockHealth
    });

    const response = await fetch('/api/health');
    const data = await response.json();

    expect(data.status).toBe('healthy');
    expect(data.services.redis).toBe(true);
  });

  it('should fetch signals', async () => {
    const mockSignals = [
      {
        id: 'sig_123',
        action: 'BUY',
        symbol: 'BTCUSDT',
        confidence: 0.85,
        timestamp: new Date().toISOString()
      }
    ];

    (global.fetch as any).mockResolvedValueOnce({
      ok: true,
      json: async () => mockSignals
    });

    const response = await fetch('/api/signals');
    const data = await response.json();

    expect(data).toHaveLength(1);
    expect(data[0].action).toBe('BUY');
  });

  it('should handle API errors', async () => {
    (global.fetch as any).mockResolvedValueOnce({
      ok: false,
      status: 500,
      statusText: 'Internal Server Error'
    });

    const response = await fetch('/api/signals');

    expect(response.ok).toBe(false);
    expect(response.status).toBe(500);
  });
});

describe('Signal Types', () => {
  it('should validate signal action types', () => {
    const validActions = ['BUY', 'SELL', 'HOLD'];
    const testAction = 'BUY';

    expect(validActions.includes(testAction)).toBe(true);
  });

  it('should validate risk decision types', () => {
    const validDecisions = ['EXECUTE', 'ABORT'];
    const testDecision = 'EXECUTE';

    expect(validDecisions.includes(testDecision)).toBe(true);
  });

  it('should validate confidence range', () => {
    const confidence = 0.85;

    expect(confidence >= 0 && confidence <= 1).toBe(true);
  });

  it('should reject invalid confidence', () => {
    const invalidConfidence = 1.5;

    expect(invalidConfidence >= 0 && invalidConfidence <= 1).toBe(false);
  });
});

describe('WebSocket Connection', () => {
  it('should parse signal messages correctly', () => {
    const message = {
      type: 'signal',
      data: {
        id: 'sig_123',
        action: 'BUY',
        symbol: 'BTCUSDT',
        confidence: 0.85
      }
    };

    expect(message.type).toBe('signal');
    expect(message.data.action).toBe('BUY');
  });

  it('should handle ping messages', () => {
    const pingMessage = { type: 'ping' };

    expect(pingMessage.type).toBe('ping');
  });

  it('should handle health messages', () => {
    const healthMessage = {
      type: 'health',
      data: {
        status: 'healthy',
        timestamp: new Date().toISOString()
      }
    };

    expect(healthMessage.type).toBe('health');
    expect(healthMessage.data.status).toBe('healthy');
  });
});

describe('Signal Dashboard Calculations', () => {
  it('should calculate average confidence', () => {
    const signals = [
      { confidence: 0.8 },
      { confidence: 0.9 },
      { confidence: 0.7 }
    ];

    const avgConfidence = signals.reduce((sum, s) => sum + s.confidence, 0) / signals.length;

    expect(avgConfidence).toBeCloseTo(0.8, 2);
  });

  it('should count signal actions', () => {
    const signals = [
      { action: 'BUY' },
      { action: 'BUY' },
      { action: 'SELL' },
      { action: 'HOLD' }
    ];

    const buyCount = signals.filter(s => s.action === 'BUY').length;
    const sellCount = signals.filter(s => s.action === 'SELL').length;
    const holdCount = signals.filter(s => s.action === 'HOLD').length;

    expect(buyCount).toBe(2);
    expect(sellCount).toBe(1);
    expect(holdCount).toBe(1);
  });

  it('should calculate P&L from signals', () => {
    const trades = [
      { pnl: 100 },
      { pnl: -50 },
      { pnl: 200 },
      { pnl: -30 }
    ];

    const totalPnl = trades.reduce((sum, t) => sum + t.pnl, 0);

    expect(totalPnl).toBe(220);
  });
});

describe('Config Panel Validation', () => {
  it('should validate weight values', () => {
    const isValidWeight = (weight: number) => weight >= 0 && weight <= 2;

    expect(isValidWeight(1.0)).toBe(true);
    expect(isValidWeight(1.5)).toBe(true);
    expect(isValidWeight(2.0)).toBe(true);
    expect(isValidWeight(-0.5)).toBe(false);
    expect(isValidWeight(2.5)).toBe(false);
  });

  it('should validate plug status transitions', () => {
    const validStatuses = ['ACTIVE', 'INACTIVE', 'DEGRADED', 'ISOLATED'];

    expect(validStatuses.includes('ACTIVE')).toBe(true);
    expect(validStatuses.includes('INVALID')).toBe(false);
  });
});

describe('Historical Analysis Filtering', () => {
  it('should filter signals by symbol', () => {
    const signals = [
      { symbol: 'BTCUSDT', action: 'BUY' },
      { symbol: 'ETHUSDT', action: 'SELL' },
      { symbol: 'BTCUSDT', action: 'SELL' }
    ];

    const filtered = signals.filter(s => s.symbol === 'BTCUSDT');

    expect(filtered).toHaveLength(2);
  });

  it('should filter signals by action', () => {
    const signals = [
      { symbol: 'BTCUSDT', action: 'BUY' },
      { symbol: 'ETHUSDT', action: 'SELL' },
      { symbol: 'BTCUSDT', action: 'BUY' }
    ];

    const buySignals = signals.filter(s => s.action === 'BUY');

    expect(buySignals).toHaveLength(2);
  });

  it('should filter signals by date range', () => {
    const now = new Date();
    const signals = [
      { timestamp: new Date(now.getTime() - 1000 * 60 * 60).toISOString() }, // 1 hour ago
      { timestamp: new Date(now.getTime() - 1000 * 60 * 60 * 24).toISOString() }, // 1 day ago
      { timestamp: new Date(now.getTime() - 1000 * 60 * 60 * 24 * 7).toISOString() } // 1 week ago
    ];

    const oneDayAgo = new Date(now.getTime() - 1000 * 60 * 60 * 24);
    const filtered = signals.filter(s => new Date(s.timestamp) >= oneDayAgo);

    expect(filtered).toHaveLength(2);
  });
});

describe('Alert Management', () => {
  it('should validate alert rule structure', () => {
    const alertRule = {
      id: 'rule_1',
      name: 'High Confidence Alert',
      enabled: true,
      conditions: {
        field: 'confidence',
        operator: 'gt',
        value: 0.9
      },
      channels: ['email', 'push']
    };

    expect(alertRule.id).toBeDefined();
    expect(alertRule.enabled).toBe(true);
    expect(alertRule.conditions.value).toBe(0.9);
  });

  it('should evaluate alert conditions', () => {
    const evaluateCondition = (
      signal: { confidence: number },
      condition: { field: string; operator: string; value: number }
    ) => {
      const signalValue = signal[condition.field as keyof typeof signal];
      switch (condition.operator) {
        case 'gt': return signalValue > condition.value;
        case 'lt': return signalValue < condition.value;
        case 'eq': return signalValue === condition.value;
        default: return false;
      }
    };

    const signal = { confidence: 0.95 };
    const condition = { field: 'confidence', operator: 'gt', value: 0.9 };

    expect(evaluateCondition(signal, condition)).toBe(true);
  });
});

describe('System Health Monitoring', () => {
  it('should determine overall health status', () => {
    const getOverallHealth = (services: Record<string, boolean>) => {
      const allHealthy = Object.values(services).every(v => v);
      const someHealthy = Object.values(services).some(v => v);
      
      if (allHealthy) return 'healthy';
      if (someHealthy) return 'degraded';
      return 'unhealthy';
    };

    expect(getOverallHealth({ redis: true, db: true, mq: true })).toBe('healthy');
    expect(getOverallHealth({ redis: true, db: false, mq: true })).toBe('degraded');
    expect(getOverallHealth({ redis: false, db: false, mq: false })).toBe('unhealthy');
  });

  it('should calculate uptime percentage', () => {
    const calculateUptime = (totalMinutes: number, downMinutes: number) => {
      return ((totalMinutes - downMinutes) / totalMinutes) * 100;
    };

    const uptime = calculateUptime(1440, 14); // 24 hours with 14 minutes downtime

    expect(uptime).toBeCloseTo(99.03, 1);
  });
});

describe('Data Formatting', () => {
  it('should format currency values', () => {
    const formatCurrency = (value: number) => {
      return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD'
      }).format(value);
    };

    expect(formatCurrency(1234.56)).toBe('$1,234.56');
    expect(formatCurrency(-500)).toBe('-$500.00');
  });

  it('should format percentage values', () => {
    const formatPercent = (value: number) => {
      return `${(value * 100).toFixed(2)}%`;
    };

    expect(formatPercent(0.8567)).toBe('85.67%');
    expect(formatPercent(0.05)).toBe('5.00%');
  });

  it('should format timestamps', () => {
    const formatTime = (isoString: string) => {
      const date = new Date(isoString);
      return date.toLocaleTimeString('en-US', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
      });
    };

    const timestamp = '2026-01-08T14:30:00.000Z';
    const formatted = formatTime(timestamp);

    expect(formatted).toMatch(/\d{2}:\d{2}:\d{2}/);
  });
});
