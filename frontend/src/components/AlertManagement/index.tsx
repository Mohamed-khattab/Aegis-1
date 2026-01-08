import { useState } from 'react';
import { Bell, BellOff, Plus, Trash2 } from 'lucide-react';

interface AlertRule {
  id: string;
  name: string;
  condition: string;
  enabled: boolean;
  channels: string[];
}

export function AlertManagement() {
  const [rules, setRules] = useState<AlertRule[]>([
    {
      id: '1',
      name: 'High Confidence Signal',
      condition: 'confidence > 0.85',
      enabled: true,
      channels: ['email', 'websocket'],
    },
    {
      id: '2',
      name: 'Risk Veto Alert',
      condition: 'risk_decision == ABORT',
      enabled: true,
      channels: ['email', 'webhook', 'websocket'],
    },
    {
      id: '3',
      name: 'Plug Isolation',
      condition: 'plug_status == ISOLATED',
      enabled: true,
      channels: ['email'],
    },
    {
      id: '4',
      name: 'Kill Switch Triggered',
      condition: 'kill_switch == true',
      enabled: true,
      channels: ['email', 'webhook', 'websocket'],
    },
  ]);

  const [showNewRuleForm, setShowNewRuleForm] = useState(false);
  const [newRule, setNewRule] = useState({
    name: '',
    condition: '',
    channels: [] as string[],
  });

  const toggleRule = (id: string) => {
    setRules((prev) =>
      prev.map((rule) =>
        rule.id === id ? { ...rule, enabled: !rule.enabled } : rule
      )
    );
  };

  const deleteRule = (id: string) => {
    setRules((prev) => prev.filter((rule) => rule.id !== id));
  };

  const addRule = () => {
    if (newRule.name && newRule.condition) {
      setRules((prev) => [
        ...prev,
        {
          id: Date.now().toString(),
          name: newRule.name,
          condition: newRule.condition,
          enabled: true,
          channels: newRule.channels,
        },
      ]);
      setNewRule({ name: '', condition: '', channels: [] });
      setShowNewRuleForm(false);
    }
  };

  const toggleChannel = (channel: string) => {
    setNewRule((prev) => ({
      ...prev,
      channels: prev.channels.includes(channel)
        ? prev.channels.filter((c) => c !== channel)
        : [...prev.channels, channel],
    }));
  };

  return (
    <div className="space-y-6">
      {/* Alert Rules */}
      <div className="card">
        <div className="card-header flex justify-between items-center">
          <div className="flex items-center space-x-2">
            <Bell className="w-5 h-5 text-gray-500" />
            <h3 className="font-semibold">Alert Rules</h3>
          </div>
          <button
            onClick={() => setShowNewRuleForm(!showNewRuleForm)}
            className="flex items-center space-x-1 text-primary-600 hover:text-primary-700 text-sm"
          >
            <Plus className="w-4 h-4" />
            <span>Add Rule</span>
          </button>
        </div>
        <div className="card-body">
          {/* New Rule Form */}
          {showNewRuleForm && (
            <div className="border rounded-lg p-4 mb-4 bg-gray-50">
              <h4 className="font-medium mb-3">New Alert Rule</h4>
              <div className="space-y-3">
                <div>
                  <label className="block text-sm text-gray-600 mb-1">
                    Rule Name
                  </label>
                  <input
                    type="text"
                    value={newRule.name}
                    onChange={(e) =>
                      setNewRule((prev) => ({ ...prev, name: e.target.value }))
                    }
                    placeholder="e.g., High Volume Alert"
                    className="w-full border rounded-md px-3 py-2 text-sm"
                  />
                </div>
                <div>
                  <label className="block text-sm text-gray-600 mb-1">
                    Condition
                  </label>
                  <input
                    type="text"
                    value={newRule.condition}
                    onChange={(e) =>
                      setNewRule((prev) => ({
                        ...prev,
                        condition: e.target.value,
                      }))
                    }
                    placeholder="e.g., confidence > 0.9"
                    className="w-full border rounded-md px-3 py-2 text-sm font-mono"
                  />
                </div>
                <div>
                  <label className="block text-sm text-gray-600 mb-1">
                    Notification Channels
                  </label>
                  <div className="flex space-x-2">
                    {['email', 'webhook', 'websocket'].map((channel) => (
                      <button
                        key={channel}
                        onClick={() => toggleChannel(channel)}
                        className={`px-3 py-1 rounded-full text-sm ${
                          newRule.channels.includes(channel)
                            ? 'bg-primary-100 text-primary-700'
                            : 'bg-gray-200 text-gray-600'
                        }`}
                      >
                        {channel}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="flex space-x-2">
                  <button
                    onClick={addRule}
                    className="bg-primary-600 text-white px-4 py-2 rounded-md text-sm hover:bg-primary-700"
                  >
                    Add Rule
                  </button>
                  <button
                    onClick={() => setShowNewRuleForm(false)}
                    className="border px-4 py-2 rounded-md text-sm hover:bg-gray-50"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Rules List */}
          <div className="space-y-3">
            {rules.map((rule) => (
              <div
                key={rule.id}
                className="border rounded-lg p-4 flex items-center justify-between"
              >
                <div className="flex items-center space-x-4">
                  <button
                    onClick={() => toggleRule(rule.id)}
                    className={`p-2 rounded-full ${
                      rule.enabled
                        ? 'bg-green-100 text-green-600'
                        : 'bg-gray-100 text-gray-400'
                    }`}
                  >
                    {rule.enabled ? (
                      <Bell className="w-4 h-4" />
                    ) : (
                      <BellOff className="w-4 h-4" />
                    )}
                  </button>
                  <div>
                    <p className="font-medium">{rule.name}</p>
                    <p className="text-sm text-gray-500 font-mono">
                      {rule.condition}
                    </p>
                    <div className="flex space-x-1 mt-1">
                      {rule.channels.map((channel) => (
                        <span
                          key={channel}
                          className="px-2 py-0.5 bg-gray-100 text-gray-600 text-xs rounded"
                        >
                          {channel}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
                <button
                  onClick={() => deleteRule(rule.id)}
                  className="p-2 text-gray-400 hover:text-red-500"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Notification Preferences */}
      <div className="card">
        <div className="card-header">
          <h3 className="font-semibold">Notification Preferences</h3>
        </div>
        <div className="card-body">
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="font-medium">Email Notifications</p>
                <p className="text-sm text-gray-500">
                  Receive alerts via email
                </p>
              </div>
              <label className="relative inline-flex items-center cursor-pointer">
                <input
                  type="checkbox"
                  defaultChecked
                  className="sr-only peer"
                />
                <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-primary-300 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-primary-600"></div>
              </label>
            </div>

            <div className="flex items-center justify-between">
              <div>
                <p className="font-medium">Push Notifications</p>
                <p className="text-sm text-gray-500">
                  Browser push notifications
                </p>
              </div>
              <label className="relative inline-flex items-center cursor-pointer">
                <input type="checkbox" className="sr-only peer" />
                <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-primary-300 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-primary-600"></div>
              </label>
            </div>

            <div className="flex items-center justify-between">
              <div>
                <p className="font-medium">Quiet Hours</p>
                <p className="text-sm text-gray-500">
                  Mute non-critical alerts
                </p>
              </div>
              <label className="relative inline-flex items-center cursor-pointer">
                <input type="checkbox" className="sr-only peer" />
                <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-primary-300 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-primary-600"></div>
              </label>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default AlertManagement;
