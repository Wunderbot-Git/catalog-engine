"use client";

import { useCallback, useEffect, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const AUTH_EMAIL = process.env.NEXT_PUBLIC_DEV_USER_EMAIL || "admin@catalog.dev";

function headers(): HeadersInit {
  return { "Content-Type": "application/json", "X-User-Email": AUTH_EMAIL };
}

interface UserData {
  id: string;
  name: string;
  email: string;
  active: boolean;
  roles: { role: string; category: string | null }[];
}

interface Thresholds {
  completeness_high: number;
  completeness_medium: number;
  richness_high: number;
  richness_medium: number;
}

export default function AdminPage() {
  const [users, setUsers] = useState<UserData[]>([]);
  const [thresholds, setThresholds] = useState<Thresholds>({
    completeness_high: 0.6, completeness_medium: 0.8,
    richness_high: 0.5, richness_medium: 0.7,
  });
  const [roleForm, setRoleForm] = useState({ userId: "", role: "", category: "" });
  const [reassignForm, setReassignForm] = useState({ skuId: "", userId: "" });
  const [confirmThresholds, setConfirmThresholds] = useState(false);

  const loadUsers = useCallback(async () => {
    const res = await fetch(`${API_BASE}/admin/users`, { headers: headers() });
    if (res.ok) setUsers(await res.json());
  }, []);

  const loadThresholds = useCallback(async () => {
    const res = await fetch(`${API_BASE}/admin/audit/thresholds`, { headers: headers() });
    if (res.ok) setThresholds(await res.json());
  }, []);

  useEffect(() => {
    loadUsers();
    loadThresholds();
  }, [loadUsers, loadThresholds]);

  const assignRole = async () => {
    const body: Record<string, string> = { role: roleForm.role };
    if (roleForm.role === "REVIEWER_CATEGORY") body.category = roleForm.category;
    await fetch(`${API_BASE}/admin/users/${roleForm.userId}/roles`, {
      method: "POST", headers: headers(), body: JSON.stringify(body),
    });
    setRoleForm({ userId: "", role: "", category: "" });
    loadUsers();
  };

  const removeRole = async (userId: string, role: string) => {
    await fetch(`${API_BASE}/admin/users/${userId}/roles`, {
      method: "DELETE", headers: headers(), body: JSON.stringify({ role }),
    });
    loadUsers();
  };

  const reassignSku = async () => {
    await fetch(`${API_BASE}/admin/assignments/${reassignForm.skuId}`, {
      method: "PUT", headers: headers(),
      body: JSON.stringify({ assigned_to_user_id: reassignForm.userId }),
    });
    setReassignForm({ skuId: "", userId: "" });
  };

  const saveThresholds = async () => {
    await fetch(`${API_BASE}/admin/audit/thresholds`, {
      method: "PUT", headers: headers(), body: JSON.stringify(thresholds),
    });
    setConfirmThresholds(false);
  };

  return (
    <div className="max-w-5xl mx-auto p-6">
      <h1 className="text-2xl font-bold mb-6">Admin Panel</h1>

      {/* User Management */}
      <section className="mb-8">
        <h2 className="text-lg font-semibold mb-3">Users</h2>
        <table className="w-full text-sm border-collapse mb-4">
          <thead>
            <tr className="border-b text-left text-gray-500">
              <th className="py-2 px-2">Name</th>
              <th className="py-2 px-2">Email</th>
              <th className="py-2 px-2">Active</th>
              <th className="py-2 px-2">Roles</th>
              <th className="py-2 px-2">Actions</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id} className="border-b">
                <td className="py-2 px-2">{u.name}</td>
                <td className="py-2 px-2">{u.email}</td>
                <td className="py-2 px-2">{u.active ? "Yes" : "No"}</td>
                <td className="py-2 px-2">
                  {u.roles.map((r) => (
                    <span key={r.role} className="inline-flex items-center gap-1 bg-gray-100 px-1.5 py-0.5 rounded text-xs mr-1">
                      {r.role}{r.category ? ` (${r.category})` : ""}
                      <button onClick={() => removeRole(u.id, r.role)} className="text-red-500 hover:text-red-700">&times;</button>
                    </span>
                  ))}
                </td>
                <td className="py-2 px-2">
                  <button
                    onClick={() => setRoleForm({ ...roleForm, userId: u.id })}
                    className="text-blue-600 text-xs hover:underline"
                  >
                    + role
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {roleForm.userId && (
          <div className="flex gap-2 items-end mb-4 p-3 border rounded">
            <div>
              <label className="text-xs text-gray-500 block">Role</label>
              <select
                value={roleForm.role}
                onChange={(e) => setRoleForm({ ...roleForm, role: e.target.value })}
                className="border rounded px-2 py-1 text-sm"
              >
                <option value="">Select...</option>
                <option value="ADMIN">ADMIN</option>
                <option value="REVIEWER_GENERAL">REVIEWER_GENERAL</option>
                <option value="REVIEWER_CATEGORY">REVIEWER_CATEGORY</option>
              </select>
            </div>
            {roleForm.role === "REVIEWER_CATEGORY" && (
              <div>
                <label className="text-xs text-gray-500 block">Category</label>
                <input
                  value={roleForm.category}
                  onChange={(e) => setRoleForm({ ...roleForm, category: e.target.value })}
                  className="border rounded px-2 py-1 text-sm"
                  placeholder="e.g. laptops"
                />
              </div>
            )}
            <button onClick={assignRole} className="px-3 py-1 bg-blue-600 text-white rounded text-sm">
              Assign
            </button>
            <button onClick={() => setRoleForm({ userId: "", role: "", category: "" })} className="px-3 py-1 border rounded text-sm">
              Cancel
            </button>
          </div>
        )}
      </section>

      {/* SKU Reassignment */}
      <section className="mb-8">
        <h2 className="text-lg font-semibold mb-3">SKU Reassignment</h2>
        <div className="flex gap-2 items-end">
          <div>
            <label htmlFor="sku-id-input" className="text-xs text-gray-500 block">SKU ID</label>
            <input
              id="sku-id-input"
              value={reassignForm.skuId}
              onChange={(e) => setReassignForm({ ...reassignForm, skuId: e.target.value })}
              className="border rounded px-2 py-1 text-sm"
            />
          </div>
          <div>
            <label className="text-xs text-gray-500 block">Assign to User</label>
            <select
              value={reassignForm.userId}
              onChange={(e) => setReassignForm({ ...reassignForm, userId: e.target.value })}
              className="border rounded px-2 py-1 text-sm"
            >
              <option value="">Select user...</option>
              {users.map((u) => (
                <option key={u.id} value={u.id}>{u.name} ({u.email})</option>
              ))}
            </select>
          </div>
          <button onClick={reassignSku} className="px-3 py-1 bg-blue-600 text-white rounded text-sm">
            Reassign
          </button>
        </div>
      </section>

      {/* Audit Thresholds */}
      <section>
        <h2 className="text-lg font-semibold mb-3">Audit Thresholds</h2>
        <div className="grid grid-cols-2 gap-3 max-w-md">
          {(["completeness_high", "completeness_medium", "richness_high", "richness_medium"] as const).map((key) => (
            <div key={key}>
              <label className="text-xs text-gray-500 block">{key}</label>
              <input
                type="number"
                step="0.1"
                min="0"
                max="1"
                value={thresholds[key]}
                onChange={(e) => setThresholds({ ...thresholds, [key]: parseFloat(e.target.value) })}
                className="border rounded px-2 py-1 text-sm w-full"
              />
            </div>
          ))}
        </div>
        <button
          onClick={() => setConfirmThresholds(true)}
          className="mt-3 px-4 py-2 bg-blue-600 text-white rounded text-sm"
        >
          Save Thresholds
        </button>
      </section>

      {/* Confirmation modal */}
      {confirmThresholds && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 w-80">
            <h3 className="font-semibold mb-2">Confirm Threshold Update</h3>
            <p className="text-sm text-gray-600 mb-4">Are you sure you want to update the audit thresholds?</p>
            <div className="flex justify-end gap-2">
              <button onClick={() => setConfirmThresholds(false)} className="px-3 py-1 border rounded text-sm">
                Cancel
              </button>
              <button onClick={saveThresholds} className="px-3 py-1 bg-blue-600 text-white rounded text-sm">
                Confirm
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
