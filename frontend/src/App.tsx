import { useState, useEffect, useCallback } from 'react';
import { SignalDashboard } from './components/SignalDashboard';
import { ConfigPanel } from './components/ConfigPanel';
import { HistoricalAnalysis } from './components/HistoricalAnalysis';
import { AlertManagement } from './components/AlertManagement';
import { SystemHealth } from './components/SystemHealth';
import { useWebSocket } from './hooks/useWebSocket';
import type { Signal, Plug } from './types';
import {
  LayoutDashboard,
  Settings,
  History,
  Bell,
  Activity,
  Wifi,
  WifiOff,
} from 'lucide-react';

type Tab = 'dashboard' | 'config' | 'history' | 'alerts' | 'health';

function App() {
  const [activeTab, setActiveTab] = useState<Tab>('dashboard');
  const [signals, setSignals] = useState<Signal[]>([]);
  const [plugStatuses, setPlugStatuses] = useState<Record<string, Plug>>({});

  const handleSignal = useCallback((signal: Signal) => {
    setSignals((prev) => [signal, ...prev].slice(0, 100));
  }, []);

  const handlePlugStatus = useCallback((status: Record<string, unknown>) => {
    setPlugStatuses(status as Record<string, Plug>);
  }, []);

  const { isConnected, sendMessage } = useWebSocket({
    onSignal: handleSignal,
    onPlugStatus: handlePlugStatus,
    onConnect: () => {
      // Request initial status
      sendMessage({ type: 'get_status' });
    },
  });

  const tabs = [
    { id: 'dashboard' as Tab, label: 'Dashboard', icon: LayoutDashboard },
    { id: 'config' as Tab, label: 'Configuration', icon: Settings },
    { id: 'history' as Tab, label: 'History', icon: History },
    { id: 'alerts' as Tab, label: 'Alerts', icon: Bell },
    { id: 'health' as Tab, label: 'System Health', icon: Activity },
  ];

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white shadow-sm border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center py-4">
            <div className="flex items-center space-x-3">
              <div className="w-10 h-10 bg-primary-600 rounded-lg flex items-center justify-center">
                <span className="text-white font-bold text-lg">A1</span>
              </div>
              <div>
                <h1 className="text-xl font-bold text-gray-900">Aegis-1</h1>
                <p className="text-xs text-gray-500">Trading System</p>
              </div>
            </div>

            <div className="flex items-center space-x-4">
              {/* Connection Status */}
              <div
                className={`flex items-center space-x-2 px-3 py-1.5 rounded-full text-sm ${
                  isConnected
                    ? 'bg-green-100 text-green-700'
                    : 'bg-red-100 text-red-700'
                }`}
              >
                {isConnected ? (
                  <Wifi className="w-4 h-4" />
                ) : (
                  <WifiOff className="w-4 h-4" />
                )}
                <span>{isConnected ? 'Connected' : 'Disconnected'}</span>
              </div>
            </div>
          </div>

          {/* Navigation */}
          <nav className="flex space-x-1 -mb-px">
            {tabs.map((tab) => {
              const Icon = tab.icon;
              const isActive = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={`flex items-center space-x-2 px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
                    isActive
                      ? 'border-primary-500 text-primary-600'
                      : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                  }`}
                >
                  <Icon className="w-4 h-4" />
                  <span>{tab.label}</span>
                </button>
              );
            })}
          </nav>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
        {activeTab === 'dashboard' && (
          <SignalDashboard signals={signals} plugStatuses={plugStatuses} />
        )}
        {activeTab === 'config' && <ConfigPanel />}
        {activeTab === 'history' && <HistoricalAnalysis />}
        {activeTab === 'alerts' && <AlertManagement />}
        {activeTab === 'health' && <SystemHealth />}
      </main>
    </div>
  );
}

export default App;
