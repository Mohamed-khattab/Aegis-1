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
  BarChart,
  Bar,
  Legend,
} from 'recharts';
import { Search, Filter } from 'lucide-react';
import { getSignals, getPlugPerformance, getPlugRanking } from '../../services/api';
import type { Signal, PlugPerformance } from '../../types';

export function HistoricalAnalysis() {
  const [signals, setSignals] = useState<Signal[]>([]);
  const [performance, setPerformance] = useState<Record<string, PlugPerformance>>({});
  const [ranking, setRanking] = useState<Array<{ plug_id: string; score: number }>>([]);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState({
    symbol: '',
    action: '',
    hours: 24,
  });

  useEffect(() => {
    loadData();
  }, [filters]);

  const loadData = async () => {
    setLoading(true);
    try {
      const [signalsData, performanceData, rankingData] = await Promise.all([
        getSignals({
          symbol: filters.symbol || undefined,
          action: filters.action || undefined,
          hours: filters.hours,
          limit: 200,
        }),
        getPlugPerformance(),
        getPlugRanking(),
      ]);
      setSignals(signalsData);
      setPerformance(performanceData);
      setRanking(rankingData);
    } catch (error) {
      console.error('Error loading historical data:', error);
    } finally {
      setLoading(false);
    }
  };

  const performanceChartData = Object.entries(performance).map(([plugId, perf]) => ({
    name: plugId.replace('_', ' '),
    accuracy: perf.rolling_accuracy * 100,
    correlation: (perf.correlation + 1) * 50, // Normalize to 0-100
    weight: perf.current_weight * 50,
  }));

  return (
    <div className="space-y-6">
      {/* Filters */}
      <div className="card">
        <div className="card-body">
          <div className="flex flex-wrap items-center gap-4">
            <div className="flex items-center space-x-2">
              <Search className="w-4 h-4 text-gray-400" />
              <input
                type="text"
                placeholder="Symbol (e.g., BTCUSDT)"
                value={filters.symbol}
                onChange={(e) =>
                  setFilters((prev) => ({ ...prev, symbol: e.target.value }))
                }
                className="border rounded-md px-3 py-2 text-sm"
              />
            </div>

            <select
              value={filters.action}
              onChange={(e) =>
                setFilters((prev) => ({ ...prev, action: e.target.value }))
              }
              className="border rounded-md px-3 py-2 text-sm"
            >
              <option value="">All Actions</option>
              <option value="BUY">BUY</option>
              <option value="SELL">SELL</option>
              <option value="HOLD">HOLD</option>
            </select>

            <select
              value={filters.hours}
              onChange={(e) =>
                setFilters((prev) => ({
                  ...prev,
                  hours: parseInt(e.target.value),
                }))
              }
              className="border rounded-md px-3 py-2 text-sm"
            >
              <option value={6}>Last 6 hours</option>
              <option value={24}>Last 24 hours</option>
              <option value={48}>Last 48 hours</option>
              <option value={168}>Last 7 days</option>
            </select>

            <button
              onClick={loadData}
              className="bg-primary-600 text-white px-4 py-2 rounded-md text-sm hover:bg-primary-700"
            >
              Apply Filters
            </button>
          </div>
        </div>
      </div>

      {/* Plug Performance Chart */}
      <div className="card">
        <div className="card-header">
          <h3 className="font-semibold">Plug Performance Comparison</h3>
        </div>
        <div className="card-body">
          <div className="h-80">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={performanceChartData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="name" />
                <YAxis />
                <Tooltip />
                <Legend />
                <Bar dataKey="accuracy" fill="#22c55e" name="Accuracy %" />
                <Bar dataKey="correlation" fill="#0ea5e9" name="Correlation" />
                <Bar dataKey="weight" fill="#f59e0b" name="Weight" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Plug Ranking */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="card">
          <div className="card-header">
            <h3 className="font-semibold">Plug Ranking</h3>
          </div>
          <div className="card-body">
            <div className="space-y-3">
              {ranking.map((item, index) => (
                <div
                  key={item.plug_id}
                  className="flex items-center justify-between p-3 bg-gray-50 rounded-lg"
                >
                  <div className="flex items-center space-x-3">
                    <span
                      className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold ${
                        index === 0
                          ? 'bg-yellow-400 text-yellow-900'
                          : index === 1
                          ? 'bg-gray-300 text-gray-700'
                          : index === 2
                          ? 'bg-amber-600 text-white'
                          : 'bg-gray-200 text-gray-600'
                      }`}
                    >
                      {index + 1}
                    </span>
                    <span className="font-medium capitalize">
                      {item.plug_id.replace('_', ' ')}
                    </span>
                  </div>
                  <span className="text-sm font-mono">
                    {(item.score * 100).toFixed(1)}%
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Performance Details */}
        <div className="card">
          <div className="card-header">
            <h3 className="font-semibold">Performance Details</h3>
          </div>
          <div className="card-body">
            <div className="space-y-4">
              {Object.entries(performance).map(([plugId, perf]) => (
                <div key={plugId} className="border-b pb-3 last:border-0">
                  <p className="font-medium capitalize mb-2">
                    {plugId.replace('_', ' ')}
                  </p>
                  <div className="grid grid-cols-2 gap-2 text-sm">
                    <div>
                      <span className="text-gray-500">Total Predictions:</span>
                      <span className="ml-2 font-mono">{perf.total_predictions}</span>
                    </div>
                    <div>
                      <span className="text-gray-500">Correct:</span>
                      <span className="ml-2 font-mono">{perf.correct_predictions}</span>
                    </div>
                    <div>
                      <span className="text-gray-500">Rolling Accuracy:</span>
                      <span className="ml-2 font-mono">
                        {(perf.rolling_accuracy * 100).toFixed(1)}%
                      </span>
                    </div>
                    <div>
                      <span className="text-gray-500">Correlation:</span>
                      <span
                        className={`ml-2 font-mono ${
                          perf.correlation > 0
                            ? 'text-green-600'
                            : 'text-red-600'
                        }`}
                      >
                        {perf.correlation.toFixed(3)}
                      </span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Signal History Table */}
      <div className="card">
        <div className="card-header">
          <h3 className="font-semibold">Signal History</h3>
          <p className="text-sm text-gray-500">{signals.length} signals</p>
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
                  Risk Score
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Decision
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {signals.map((signal) => (
                <tr key={signal.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-sm text-gray-500">
                    {format(new Date(signal.timestamp), 'MMM d, HH:mm:ss')}
                  </td>
                  <td className="px-4 py-3 text-sm font-medium">{signal.symbol}</td>
                  <td className="px-4 py-3">
                    <span
                      className={`px-2 py-1 rounded-full text-xs font-medium ${
                        signal.action === 'BUY'
                          ? 'bg-green-100 text-green-700'
                          : signal.action === 'SELL'
                          ? 'bg-red-100 text-red-700'
                          : 'bg-gray-100 text-gray-700'
                      }`}
                    >
                      {signal.action}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm">
                    {(signal.confidence * 100).toFixed(1)}%
                  </td>
                  <td className="px-4 py-3 text-sm">
                    {(signal.risk_score * 100).toFixed(1)}%
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`text-sm ${
                        signal.risk_decision === 'EXECUTE'
                          ? 'text-green-600'
                          : 'text-red-600'
                      }`}
                    >
                      {signal.risk_decision}
                    </span>
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

export default HistoricalAnalysis;
