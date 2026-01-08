import { useState, useEffect } from 'react';
import { Settings, RefreshCw, Save } from 'lucide-react';
import {
  getPlugs,
  getWeights,
  updatePlugWeight,
  updatePlugStatus,
  resetWeights,
  getOutputs,
  enableOutput,
  disableOutput,
} from '../../services/api';
import type { Plug, Output } from '../../types';

export function ConfigPanel() {
  const [plugs, setPlugs] = useState<Record<string, Plug>>({});
  const [weights, setWeights] = useState<Record<string, number>>({});
  const [outputs, setOutputs] = useState<Record<string, Output>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    setLoading(true);
    try {
      const [plugsData, weightsData, outputsData] = await Promise.all([
        getPlugs(),
        getWeights(),
        getOutputs(),
      ]);
      setPlugs(plugsData);
      setWeights(weightsData);
      setOutputs(outputsData);
    } catch (error) {
      console.error('Error loading config:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleWeightChange = async (plugId: string, weight: number) => {
    setWeights((prev) => ({ ...prev, [plugId]: weight }));
    try {
      await updatePlugWeight(plugId, weight);
    } catch (error) {
      console.error('Error updating weight:', error);
    }
  };

  const handlePlugToggle = async (plugId: string, enabled: boolean) => {
    try {
      await updatePlugStatus(plugId, enabled);
      await loadData();
    } catch (error) {
      console.error('Error toggling plug:', error);
    }
  };

  const handleOutputToggle = async (outputId: string, enabled: boolean) => {
    try {
      if (enabled) {
        await enableOutput(outputId);
      } else {
        await disableOutput(outputId);
      }
      await loadData();
    } catch (error) {
      console.error('Error toggling output:', error);
    }
  };

  const handleResetWeights = async () => {
    try {
      await resetWeights();
      await loadData();
    } catch (error) {
      console.error('Error resetting weights:', error);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <RefreshCw className="w-8 h-8 animate-spin text-primary-500" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Plug Configuration */}
      <div className="card">
        <div className="card-header flex justify-between items-center">
          <div className="flex items-center space-x-2">
            <Settings className="w-5 h-5 text-gray-500" />
            <h3 className="font-semibold">Plug Configuration</h3>
          </div>
          <button
            onClick={handleResetWeights}
            className="text-sm text-primary-600 hover:text-primary-700 flex items-center space-x-1"
          >
            <RefreshCw className="w-4 h-4" />
            <span>Reset Weights</span>
          </button>
        </div>
        <div className="card-body">
          <div className="space-y-4">
            {Object.entries(plugs).map(([plugId, plug]) => (
              <div
                key={plugId}
                className="border rounded-lg p-4 flex flex-col md:flex-row md:items-center justify-between space-y-4 md:space-y-0"
              >
                <div className="flex items-center space-x-4">
                  <div
                    className={`w-3 h-3 rounded-full ${
                      plug.status === 'ACTIVE'
                        ? 'bg-green-500'
                        : plug.status === 'ISOLATED'
                        ? 'bg-red-500'
                        : 'bg-gray-400'
                    }`}
                  />
                  <div>
                    <p className="font-medium capitalize">
                      {plugId.replace('_', ' ')}
                    </p>
                    <p className="text-sm text-gray-500">
                      Status: {plug.status} | Accuracy:{' '}
                      {(plug.metrics.accuracy * 100).toFixed(1)}%
                    </p>
                  </div>
                </div>

                <div className="flex items-center space-x-6">
                  {/* Weight Slider */}
                  <div className="flex items-center space-x-3">
                    <label className="text-sm text-gray-600">Weight:</label>
                    <input
                      type="range"
                      min="0"
                      max="2"
                      step="0.1"
                      value={weights[plugId] || 1}
                      onChange={(e) =>
                        handleWeightChange(plugId, parseFloat(e.target.value))
                      }
                      className="w-24"
                    />
                    <span className="text-sm font-medium w-12">
                      {(weights[plugId] || 1).toFixed(1)}
                    </span>
                  </div>

                  {/* Enable/Disable Toggle */}
                  <label className="relative inline-flex items-center cursor-pointer">
                    <input
                      type="checkbox"
                      checked={plug.status === 'ACTIVE'}
                      onChange={(e) => handlePlugToggle(plugId, e.target.checked)}
                      className="sr-only peer"
                    />
                    <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-primary-300 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-primary-600"></div>
                  </label>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Output Configuration */}
      <div className="card">
        <div className="card-header">
          <h3 className="font-semibold">Output Configuration</h3>
        </div>
        <div className="card-body">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {Object.entries(outputs).map(([outputId, output]) => (
              <div key={outputId} className="border rounded-lg p-4">
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center space-x-2">
                    <div
                      className={`w-2 h-2 rounded-full ${
                        output.status === 'ACTIVE'
                          ? 'bg-green-500'
                          : output.status === 'ERROR'
                          ? 'bg-red-500'
                          : 'bg-gray-400'
                      }`}
                    />
                    <p className="font-medium capitalize">
                      {outputId.replace('_', ' ')}
                    </p>
                  </div>
                  <label className="relative inline-flex items-center cursor-pointer">
                    <input
                      type="checkbox"
                      checked={output.enabled}
                      onChange={(e) =>
                        handleOutputToggle(outputId, e.target.checked)
                      }
                      className="sr-only peer"
                    />
                    <div className="w-9 h-5 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-primary-300 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-primary-600"></div>
                  </label>
                </div>
                <div className="text-sm text-gray-500 space-y-1">
                  <p>Sent: {output.metrics.signals_sent}</p>
                  <p>Success Rate: {(output.metrics.success_rate * 100).toFixed(1)}%</p>
                  <p>Avg Latency: {output.metrics.avg_delivery_time_ms.toFixed(0)}ms</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

export default ConfigPanel;
