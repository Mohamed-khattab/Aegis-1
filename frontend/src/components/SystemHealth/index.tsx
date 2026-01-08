import { useState, useEffect } from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import {
  Activity,
  Database,
  Server,
  Cpu,
  HardDrive,
  Wifi,
  CheckCircle,
  XCircle,
  AlertTriangle,
  RefreshCw,
} from 'lucide-react';
import { getHealth, getStatus, getRiskSummary } from '../../services/api';
import type { HealthStatus, SystemStatus, RiskSummary } from '../../types';

export function SystemHealth() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [riskSummary, setRiskSummary] = useState<RiskSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [latencyHistory, setLatencyHistory] = useState<Array<{ time: string; latency: number }>>([]);

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 10000); // Refresh every 10 seconds
    return () => clearInterval(interval);
  }, []);

  const loadData = async () => {
    try {
      const [healthData, statusData, riskData] = await Promise.all([
        getHealth(),
        getStatus(),
        getRiskSummary(),
      ]);
      setHealth(healthData);
      setStatus(statusData);
      setRiskSummary(riskData);

      // Simulate latency history
      setLatencyHistory((prev) => {
        const now = new Date();
        const newEntry = {
          time: now.toLocaleTimeString(),
          latency: Math.random() * 50 + 10,
        };
        return [...prev.slice(-20), newEntry];
      });
    } catch (error) {
      console.error('Error loading health data:', error);
    } finally {
      setLoading(false);
    }
  };

  const getStatusIcon = (isHealthy: boolean) => {
    return isHealthy ? (
      <CheckCircle className="w-5 h-5 text-green-500" />
    ) : (
      <XCircle className="w-5 h-5 text-red-500" />
    );
  };

  if (loading && !health) {
    return (
      <div className="flex items-center justify-center h-64">
        <RefreshCw className="w-8 h-8 animate-spin text-primary-500" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Overall Status */}
      <div className="card">
        <div className="card-header flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <Activity className="w-5 h-5 text-gray-500" />
            <h3 className="font-semibold">System Status</h3>
          </div>
          <span
            className={`px-3 py-1 rounded-full text-sm font-medium ${
              health?.status === 'healthy'
                ? 'bg-green-100 text-green-700'
                : health?.status === 'degraded'
                ? 'bg-yellow-100 text-yellow-700'
                : 'bg-red-100 text-red-700'
            }`}
          >
            {health?.status?.toUpperCase() || 'UNKNOWN'}
          </span>
        </div>
        <div className="card-body">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {health?.components &&
              Object.entries(health.components).map(([name, isHealthy]) => (
                <div
                  key={name}
                  className="flex items-center space-x-3 p-3 border rounded-lg"
                >
                  {getStatusIcon(isHealthy)}
                  <span className="capitalize">{name}</span>
                </div>
              ))}
          </div>
        </div>
      </div>

      {/* Latency Chart */}
      <div className="card">
        <div className="card-header">
          <h3 className="font-semibold">System Latency</h3>
        </div>
        <div className="card-body">
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={latencyHistory}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="time" />
                <YAxis unit="ms" />
                <Tooltip />
                <Line
                  type="monotone"
                  dataKey="latency"
                  stroke="#0ea5e9"
                  strokeWidth={2}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Component Details */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Database Status */}
        <div className="card">
          <div className="card-header flex items-center space-x-2">
            <Database className="w-5 h-5 text-gray-500" />
            <h3 className="font-semibold">Database</h3>
          </div>
          <div className="card-body">
            <div className="space-y-3">
              <div className="flex justify-between">
                <span className="text-gray-600">TimescaleDB</span>
                {getStatusIcon(health?.components?.database || false)}
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">Redis</span>
                {getStatusIcon(health?.components?.redis || false)}
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">Connection Pool</span>
                <span className="text-gray-700">20 / 50 active</span>
              </div>
            </div>
          </div>
        </div>

        {/* Risk Status */}
        <div className="card">
          <div className="card-header flex items-center space-x-2">
            <AlertTriangle className="w-5 h-5 text-gray-500" />
            <h3 className="font-semibold">Risk Monitor</h3>
          </div>
          <div className="card-body">
            <div className="space-y-3">
              <div className="flex justify-between">
                <span className="text-gray-600">Portfolio Value</span>
                <span className="font-medium">
                  ${riskSummary?.portfolio_value?.toLocaleString() || '0'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">Current Drawdown</span>
                <span
                  className={`font-medium ${
                    (riskSummary?.current_drawdown || 0) > 0.03
                      ? 'text-red-600'
                      : 'text-green-600'
                  }`}
                >
                  {((riskSummary?.current_drawdown || 0) * 100).toFixed(2)}%
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">Session P&L</span>
                <span
                  className={`font-medium ${
                    (riskSummary?.session_pnl_percent || 0) >= 0
                      ? 'text-green-600'
                      : 'text-red-600'
                  }`}
                >
                  {(riskSummary?.session_pnl_percent || 0) >= 0 ? '+' : ''}
                  {(riskSummary?.session_pnl_percent || 0).toFixed(2)}%
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-600">Kill Switch</span>
                <span className="text-green-600">Armed</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Plug Status Grid */}
      <div className="card">
        <div className="card-header">
          <h3 className="font-semibold">Plug Health</h3>
        </div>
        <div className="card-body">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {status?.plugs &&
              Object.entries(status.plugs).map(([plugId, plug]) => (
                <div key={plugId} className="border rounded-lg p-4">
                  <div className="flex items-center justify-between mb-2">
                    <span className="font-medium capitalize">
                      {plugId.replace('_', ' ')}
                    </span>
                    <div
                      className={`w-2 h-2 rounded-full ${
                        plug.status === 'ACTIVE'
                          ? 'bg-green-500'
                          : plug.status === 'ISOLATED'
                          ? 'bg-red-500'
                          : 'bg-gray-400'
                      }`}
                    />
                  </div>
                  <div className="text-sm text-gray-500 space-y-1">
                    <p>Signals: {plug.metrics.total_signals}</p>
                    <p>
                      Latency: {plug.metrics.avg_latency_ms.toFixed(0)}ms
                    </p>
                    <p>
                      Accuracy: {(plug.metrics.accuracy * 100).toFixed(1)}%
                    </p>
                  </div>
                </div>
              ))}
          </div>
        </div>
      </div>
    </div>
  );
}

export default SystemHealth;
