"use client";

import { useState } from "react";
import { createKey, fetchKeys, revokeKey } from "@/lib/api";

type APIKey = {
  id: string;
  key_prefix: string;
  name: string | null;
  created_at: string;
  last_used_at: string | null;
  revoked: boolean;
};

type NewKeyResult = APIKey & { raw_key: string };

export default function APIKeysPage() {
  const [keys, setKeys] = useState<APIKey[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [newKeyName, setNewKeyName] = useState("");
  const [newKey, setNewKey] = useState<NewKeyResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function loadKeys(apiKey: string) {
    try {
      const data = await fetchKeys(apiKey);
      setKeys(data);
      setLoaded(true);
    } catch (e) {
      setError("Failed to load keys. Make sure your API key is valid.");
    }
  }

  // In a real app, the active API key comes from the user session / Clerk JWT.
  // For Week 2 we expose a manual input to demonstrate the flow.
  const [activeKey, setActiveKey] = useState("");

  async function handleCreate() {
    if (!activeKey) return;
    setLoading(true);
    setError("");
    try {
      const created: NewKeyResult = await createKey(activeKey, newKeyName || undefined);
      setNewKey(created);
      setNewKeyName("");
      await loadKeys(activeKey);
    } catch (e) {
      setError("Failed to create key.");
    } finally {
      setLoading(false);
    }
  }

  async function handleRevoke(keyId: string) {
    if (!activeKey) return;
    setLoading(true);
    try {
      await revokeKey(activeKey, keyId);
      setKeys((prev) => prev.filter((k) => k.id !== keyId));
    } catch (e) {
      setError("Failed to revoke key.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="p-8 max-w-3xl">
      <h1 className="text-2xl font-bold mb-6">API Keys</h1>

      {/* Active key input — placeholder until server-side session wiring in Week 3 */}
      <div className="mb-6 p-4 rounded-lg border border-gray-200 bg-gray-50">
        <label className="block text-sm font-medium text-gray-700 mb-1">
          Your active API key (to authenticate this request)
        </label>
        <div className="flex gap-2">
          <input
            type="text"
            placeholder="sk_live_..."
            value={activeKey}
            onChange={(e) => setActiveKey(e.target.value)}
            className="flex-1 px-3 py-2 border border-gray-300 rounded-md text-sm font-mono"
          />
          <button
            onClick={() => loadKeys(activeKey)}
            className="px-4 py-2 bg-gray-800 text-white rounded-md text-sm hover:bg-gray-700"
          >
            Load keys
          </button>
        </div>
      </div>

      {error && <p className="text-red-500 text-sm mb-4">{error}</p>}

      {/* New key dialog */}
      {newKey && (
        <div className="mb-6 p-4 rounded-lg border border-green-300 bg-green-50">
          <p className="font-medium text-green-800 mb-2">New key created — copy it now, it won&apos;t be shown again.</p>
          <code className="block p-2 bg-white border border-green-200 rounded text-sm font-mono break-all">
            {newKey.raw_key}
          </code>
          <button
            onClick={() => { navigator.clipboard.writeText(newKey.raw_key); }}
            className="mt-2 text-xs text-green-700 underline"
          >
            Copy to clipboard
          </button>
          <button
            onClick={() => setNewKey(null)}
            className="mt-2 ml-4 text-xs text-gray-500 underline"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Create form */}
      <div className="mb-8 flex gap-2">
        <input
          type="text"
          placeholder="Key name (optional)"
          value={newKeyName}
          onChange={(e) => setNewKeyName(e.target.value)}
          className="flex-1 px-3 py-2 border border-gray-300 rounded-md text-sm"
        />
        <button
          onClick={handleCreate}
          disabled={loading || !activeKey}
          className="px-4 py-2 bg-indigo-600 text-white rounded-md text-sm hover:bg-indigo-500 disabled:opacity-50"
        >
          {loading ? "Creating..." : "Create key"}
        </button>
      </div>

      {/* Keys table */}
      {loaded && (
        <div className="overflow-x-auto rounded-lg border border-gray-200">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="text-left px-4 py-3 font-medium text-gray-600">Name</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">Prefix</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">Created</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600">Last used</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {keys.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-6 text-center text-gray-400">
                    No active keys. Create one above.
                  </td>
                </tr>
              )}
              {keys.map((k) => (
                <tr key={k.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-gray-800">{k.name ?? <span className="text-gray-400">—</span>}</td>
                  <td className="px-4 py-3 font-mono text-gray-600">{k.key_prefix}...</td>
                  <td className="px-4 py-3 text-gray-500">{new Date(k.created_at).toLocaleDateString()}</td>
                  <td className="px-4 py-3 text-gray-500">
                    {k.last_used_at ? new Date(k.last_used_at).toLocaleDateString() : "Never"}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={() => handleRevoke(k.id)}
                      className="text-red-500 hover:text-red-700 text-xs font-medium"
                    >
                      Revoke
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
