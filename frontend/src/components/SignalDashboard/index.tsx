import { useState, useEffect } from 'react';
import { format } from 'date-fns';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
} from 'recharts';
import {
  TrendingUp,
  TrendingDown,
  Minus,
  AlertTriangle,
  CheckCircle,
  XCircle,
} from 'lucide-react';
import type { Signal, Plug } from '../../types';
import { getSignalStats, getRiskSummary } from '../../services/api';

interface SignalDashboardProps {
  signals: Signal[];
  plugStatuses: Record<string, Plug>;
}

export function SignalDashboard({ signals, plugStatuses }: SignalDashboardProps) {
  const [stats, setStats] = useState({
    total_signals: 0,
    avg_confidence: 0,
    buy_count: 0,
    sell_count: 0,
    hold_count: 0,
    aborted_count: 0,
  });
  const [riskSummary, setRiskSummary] = useState({
    portfolio_value: 0,
    current_drawdown: 0,
    session_pnl_percent: 0,
  });

  useEffect(() => {
    // Fetch stats
    getSignalStats('ALL', 24).then(setStats).catch(console.error);
    getRiskSummary().then(setRiskSummary).catch(console.error);
  }, [signals]);

  const actionColors: Record<string, string> = {
    BUY: '#22c55e',
    SELL: '#ef4444',
    HOLD: '#6b7280',
  };

  const pieData = [
    { name: 'Buy', value: stats.buy_count, color: actionColors.BUY },
    { name: 'Sell', value: stats.sell_count, color: actionColors.SELL },
    { name: 'Hold', value: stats.hold_count, color: actionColors.HOLD },
  ];

  const getActionIcon = (action: string) => {
    switch (action) {
      case 'BUY':
        return <TrendingUp className="w-5 h-5 text-green-500" />;
      case 'SELL':
        return <TrendingDown className="w-5 h-5 text-red-500" />;
      default:
        return <Minus className="w-5 h-5 text-gray-500" />;
    }
  };

  const getDecisionIcon = (decision: string) => {
    return decision === 'EXECUTE' ? (
      <CheckCircle className="w-4 h-4 text-green-500" />
    ) : (
      <XCircle className="w-4 h-4 text-red-500" />
    );
  };

  return (
    <div className="space-y-6">
      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className="card">
          <div className="card-body">
            <p className="text-sm text-gray-500">Total Signals (24h)</p>
            <p className="text-2xl font-bold">{stats.total_signals}</p>
          </div>
        </div>
        <div className="card">
          <div className="card-body">
            <p className="text-sm text-gray-500">Avg Confidence</p>
            <p className="text-2xl font-bold">
              {(stats.avg_confidence * 100).toFixed(1)}%
            </p>
          </div>
        </div>
        <div className="card">
          <div className="card-body">
            <p className="text-sm text-gray-500">Session P&L</p>
            <p
              className={`text-2xl font-bold ${
                riskSummary.session_pnl_percent >= 0
                  ? 'text-green-600'
                  : 'text-red-600'
              }`}
            >
              {riskSummary.session_pnl_percent >= 0 ? '+' : ''}
              {riskSummary.session_pnl_percent.toFixed(2)}%
            </p>
          </div>
        </div>
        <div className="card">
          <div className="card-body">
            <p className="text-sm text-gray-500">Current Drawdown</p>
            <p className="text-2xl font-bold text-amber-600">
              {(riskSummary.current_drawdown * 100).toFixed(2)}%
            </p>
          </div>
        </div>
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Confidence Chart */}
        <div className="lg:col-span-2 card">
          <div className="card-header">
            <h3 className="font-semibold">Signal Confidence Over Time</h3>
          </div>
          <div className="card-body">
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart
                  data={signals.slice(0, 20).reverse().map((s) => ({
                    time: format(new Date(s.timestamp), 'HH:mm'),
                    confidence: s.confidence * 100,
                    risk: s.risk_score * 100,
                  }))}
                >
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="time" />
                  <YAxis domain={[0, 100]} />
                  <Tooltip />
                  <Line
                    type="monotone"
                    dataKey="confidence"
                    stroke="#0ea5e9"
                    strokeWidth={2}
                    dot={false}
                    name="Confidence"
                  />
                  <Line
                    type="monotone"
                    dataKey="risk"
                    stroke="#f59e0b"
                    strokeWidth={2}
                    dot={false}
                    name="Risk Score"
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>

        {/* Action Distribution */}
        <div className="card">
          <div className="card-header">
            <h3 className="font-semibold">Signal Distribution</h3>
          </div>
          <div className="card-body">
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={pieData}
                    cx="50%"
                    cy="50%"
                    innerRadius={60}
                    outerRadius={80}
                    paddingAngle={5}
                    dataKey="value"
                    label={({ name, percent }) =>
                      `${name} ${(percent * 100).toFixed(0)}%`
                    }
                  >
                    {pieData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.color} />
                    ))}
                  </Pie>
                  <Tooltip />
                </PieChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
      </div>

      {/* Plug Status */}
      <div className="card">
        <div className="card-header">
          <h3 className="font-semibold">Plug Status</h3>
        </div>
        <div className="card-body">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {Object.entries(plugStatuses).map(([id, plug]) => (
              <div
                key={id}
                className="border rounded-lg p-3 flex items-center justify-between"
              >
                <div>
                  <p className="font-medium capitalize">{id.replace('_', ' ')}</p>
                  <p className="text-sm text-gray-500">
                    Weight: {plug.weight.toFixed(2)}
                  </p>
                </div>
                <div
                  className={`status-dot ${
                    plug.status === 'ACTIVE'
                      ? 'status-active'
                      : plug.status === 'ISOLATED'
                      ? 'status-error'
                      : 'status-inactive'
                  }`}
                />
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Recent Signals */}
      <div className="card">
        <div className="card-header flex justify-between items-center">
          <h3 className="font-semibold">Recent Signals</h3>
          <span className="text-sm text-gray-500">{signals.length} signals</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Time
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Symbol
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Action
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Confidence
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Risk
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Decision
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {signals.slice(0, 10).map((signal) => (
                <tr key={signal.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-sm text-gray-500">
                    {format(new Date(signal.timestamp), 'HH:mm:ss')}
                  </td>
                  <td className="px-4 py-3 text-sm font-medium">{signal.symbol}</td>
                  <td className="px-4 py-3">
                    <div className="flex items-center space-x-2">
                      {getActionIcon(signal.action)}
                      <span
                        className={`text-sm font-medium ${
                          signal.action === 'BUY'
                            ? 'text-green-600'
                            : signal.action === 'SELL'
                            ? 'text-red-600'
                            : 'text-gray-600'
                        }`}
                      >
                        {signal.action}
                      </span>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center">
                      <div className="w-16 bg-gray-200 rounded-full h-2 mr-2">
                        <div
                          className="bg-primary-500 h-2 rounded-full"
                          style={{ width: `${signal.confidence * 100}%` }}
                        />
                      </div>
                      <span className="text-sm">
                        {(signal.confidence * 100).toFixed(0)}%
                      </span>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`text-sm ${
                        signal.risk_score > 0.7
                          ? 'text-red-600'
                          : signal.risk_score > 0.4
                          ? 'text-amber-600'
                          : 'text-green-600'
                      }`}
                    >
                      {(signal.risk_score * 100).toFixed(0)}%
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center space-x-1">
                      {getDecisionIcon(signal.risk_decision)}
                      <span className="text-sm">{signal.risk_decision}</span>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

export default SignalDashboard;
