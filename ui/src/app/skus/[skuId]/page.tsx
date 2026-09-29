"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import ChipInput from "@/components/ChipInput";
import ScoreBar from "@/components/ScoreBar";
import { fetchSku, fetchVersions, fetchUsers, fetchComments, submitReview, UserInfo, CommentEntry } from "@/lib/api";
import { SkuDetail, SuggestedAttribute, VersionEntry } from "@/types/api";

interface EditState {
  use_case_tags: string[];
  persona_tags: string[];
  trust_signals: {
    warranty_months: number | null;
    certifications: string[];
    sustainability_notes: string;
  };
  agent_summary: string;
  confidence_score: number;
  evidence_fields: string[];
  suggested_attributes: SuggestedAttribute[];
}

function hasInvalidSuggestion(e: EditState): boolean {
  return e.suggested_attributes.some(
    (s) => s.source === "product_text" && (s.value === null || String(s.value).trim() === "")
  );
}

function enrichmentToEdit(e: SkuDetail["enrichment"]): EditState | null {
  if (!e) return null;
  const ts = e.trust_signals as Record<string, unknown>;
  return {
    use_case_tags: [...e.use_case_tags],
    persona_tags: [...e.persona_tags],
    trust_signals: {
      warranty_months: (ts.warranty_months as number) ?? null,
      certifications: (ts.certifications as string[]) ?? [],
      sustainability_notes: (ts.sustainability_notes as string) ?? "",
    },
    agent_summary: e.agent_summary,
    confidence_score: e.confidence_score,
    evidence_fields: [...e.evidence_fields],
    suggested_attributes: (e.suggested_attributes ?? []).map((s) => ({ ...s })),
  };
}

export default function ReviewWorkspace() {
  const params = useParams();
  const router = useRouter();
  const skuId = params.skuId as string;

  const [sku, setSku] = useState<SkuDetail | null>(null);
  const [versions, setVersions] = useState<VersionEntry[]>([]);
  const [edit, setEdit] = useState<EditState | null>(null);
  const [dirty, setDirty] = useState(false);
  const [activeTab, setActiveTab] = useState<"history" | "comments">("history");
  const [rejectModal, setRejectModal] = useState(false);
  const [rejectReason, setRejectReason] = useState("");
  const [reenrichModal, setReenrichModal] = useState(false);
  const [reenrichFeedback, setReenrichFeedback] = useState("");
  const [escalateModal, setEscalateModal] = useState(false);
  const [escalateUserId, setEscalateUserId] = useState("");
  const [escalateReason, setEscalateReason] = useState("");
  const [users, setUsers] = useState<UserInfo[]>([]);
  const [comments, setComments] = useState<CommentEntry[]>([]);
  const [commentBody, setCommentBody] = useState("");
  const [commentType, setCommentType] = useState("NOTE");
  const [diffVersionId, setDiffVersionId] = useState<string | null>(null);
  const [toast, setToast] = useState("");
  const autoSaveRef = useRef<ReturnType<typeof setInterval>>(undefined);

  const load = useCallback(async () => {
    const [s, v, c] = await Promise.all([
      fetchSku(skuId),
      fetchVersions(skuId),
      fetchComments(skuId).catch(() => [] as CommentEntry[]),
    ]);
    setSku(s);
    setVersions(v);
    setComments(c);

    // Restore draft or initialize from enrichment
    const draftKey = `draft-${skuId}`;
    const saved = localStorage.getItem(draftKey);
    if (saved) {
      const draft = JSON.parse(saved);
      setEdit({ ...draft, suggested_attributes: draft.suggested_attributes ?? [] });
      setDirty(true);
    } else {
      setEdit(enrichmentToEdit(s.enrichment));
      setDirty(false);
    }
  }, [skuId]);

  useEffect(() => {
    load();
  }, [load]);

  // Auto-save every 30s
  useEffect(() => {
    autoSaveRef.current = setInterval(() => {
      if (dirty && edit) {
        localStorage.setItem(`draft-${skuId}`, JSON.stringify(edit));
        setToast("Draft saved");
        setTimeout(() => setToast(""), 2000);
      }
    }, 30000);
    return () => clearInterval(autoSaveRef.current);
  }, [dirty, edit, skuId]);

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      if (e.key === "a") handleApprove();
      else if (e.key === "r") setRejectModal(true);
      else if (e.key === "[") router.back();
      else if (e.key === "]") router.forward();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  });

  const versionId = sku?.enrichment?.version_id;

  const handleApprove = async () => {
    if (!versionId) return;
    await submitReview(skuId, { action: "approve", version_id: versionId });
    localStorage.removeItem(`draft-${skuId}`);
    load();
  };

  const handleApproveWithEdits = async () => {
    if (!versionId || !edit || hasInvalidSuggestion(edit)) return;
    await submitReview(skuId, {
      action: "approve_with_edits",
      version_id: versionId,
      edited_enrichment: edit,
    });
    localStorage.removeItem(`draft-${skuId}`);
    setDirty(false);
    load();
  };

  const handleReject = async () => {
    if (!versionId || rejectReason.length < 10) return;
    await submitReview(skuId, {
      action: "reject",
      version_id: versionId,
      rejection_reason: rejectReason,
    });
    setRejectModal(false);
    setRejectReason("");
    load();
  };

  const handleReenrich = async () => {
    if (!versionId) return;
    await submitReview(skuId, {
      action: "reenrich",
      version_id: versionId,
      reenrich_feedback: reenrichFeedback,
    });
    setReenrichModal(false);
    setReenrichFeedback("");
    load();
  };

  const handleEscalate = async () => {
    if (!versionId || !escalateUserId || !escalateReason) return;
    await submitReview(skuId, {
      action: "escalate",
      version_id: versionId,
      escalate_to_user_id: escalateUserId,
      escalate_reason: escalateReason,
    });
    setEscalateModal(false);
    setEscalateUserId("");
    setEscalateReason("");
    load();
  };

  const openEscalateModal = async () => {
    if (users.length === 0) {
      const u = await fetchUsers().catch(() => [] as UserInfo[]);
      setUsers(u);
    }
    setEscalateModal(true);
  };

  const handleComment = async () => {
    if (!versionId || !commentBody.trim()) return;
    await submitReview(skuId, {
      action: "comment",
      version_id: versionId,
      comment_type: commentType,
      comment_body: commentBody,
    });
    setCommentBody("");
    load();
  };

  const handleSaveDraft = () => {
    if (edit) {
      localStorage.setItem(`draft-${skuId}`, JSON.stringify(edit));
      setToast("Draft saved");
      setTimeout(() => setToast(""), 2000);
    }
  };

  const updateEdit = (patch: Partial<EditState>) => {
    setEdit((prev) => (prev ? { ...prev, ...patch } : prev));
    setDirty(true);
  };

  const updateSuggestionValue = (index: number, raw: string) => {
    if (!edit) return;
    const next = edit.suggested_attributes.map((s, i) => {
      if (i !== index) return s;
      // Store canonical numbers ("15.6") as numbers; partial input ("15.") stays text.
      const asNumber = Number(raw);
      const isNumber = raw.trim() !== "" && String(asNumber) === raw.trim();
      return { ...s, value: isNumber ? asNumber : raw };
    });
    updateEdit({ suggested_attributes: next });
  };

  const removeSuggestion = (index: number) => {
    if (!edit) return;
    updateEdit({ suggested_attributes: edit.suggested_attributes.filter((_, i) => i !== index) });
  };

  if (!sku) return <div className="p-6">Loading...</div>;

  const summaryLen = edit?.agent_summary.length ?? 0;
  const summaryColor = summaryLen >= 240 ? "text-red-600" : summaryLen >= 200 ? "text-yellow-600" : "text-gray-400";

  return (
    <div className="max-w-7xl mx-auto p-6">
      {toast && (
        <div className="fixed top-4 right-4 bg-green-600 text-white px-4 py-2 rounded shadow z-50">
          {toast}
        </div>
      )}

      <h1 className="text-xl font-bold mb-4">{sku.sku_id} — {sku.title}</h1>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Panel 1: Product */}
        <div className="border rounded-lg p-4">
          <h2 className="font-semibold mb-2">Product</h2>
          <dl className="grid grid-cols-2 gap-2 text-sm">
            <dt className="text-gray-500">Brand</dt><dd>{sku.brand}</dd>
            <dt className="text-gray-500">Category</dt><dd>{sku.category}</dd>
            <dt className="text-gray-500">Price</dt><dd>${sku.price.toFixed(2)}</dd>
          </dl>
          {sku.attributes && Object.keys(sku.attributes).length > 0 && (
            <div className="mt-3">
              <p className="text-xs font-medium text-gray-500 mb-1">Attributes</p>
              <dl className="grid grid-cols-2 gap-1 text-xs">
                {Object.entries(sku.attributes).map(([k, v]) => (
                  <div key={k}><dt className="text-gray-500 inline">{k}:</dt> <dd className="inline">{String(v)}</dd></div>
                ))}
              </dl>
            </div>
          )}
        </div>

        {/* Panel 2: Audit */}
        <div className="border rounded-lg p-4">
          <h2 className="font-semibold mb-2">Audit</h2>
          {sku.audit ? (
            <div className="space-y-3">
              <ScoreBar label="Completeness" value={sku.audit.completeness_score} />
              <ScoreBar label="Richness" value={sku.audit.richness_score} />
              {sku.audit.missing_critical_fields.length > 0 && (
                <div>
                  <p className="text-xs text-gray-500">Missing fields</p>
                  <ul className="text-xs text-red-600">
                    {sku.audit.missing_critical_fields.map((f) => <li key={f}>{f}</li>)}
                  </ul>
                </div>
              )}
            </div>
          ) : (
            <p className="text-sm text-gray-400">No audit data</p>
          )}
        </div>

        {/* Panel 3: Enrichment editor */}
        <div className="border rounded-lg p-4">
          <h2 className="font-semibold mb-2">Enrichment</h2>
          {edit ? (
            <div className="space-y-3">
              <ChipInput
                label="Use Case Tags"
                value={edit.use_case_tags}
                onChange={(tags) => updateEdit({ use_case_tags: tags })}
              />
              <ChipInput
                label="Persona Tags"
                value={edit.persona_tags}
                onChange={(tags) => updateEdit({ persona_tags: tags })}
              />
              <div>
                <label className="text-xs font-medium text-gray-500">Warranty (months)</label>
                <input
                  type="number"
                  value={edit.trust_signals.warranty_months ?? ""}
                  onChange={(e) =>
                    updateEdit({
                      trust_signals: {
                        ...edit.trust_signals,
                        warranty_months: e.target.value ? Number(e.target.value) : null,
                      },
                    })
                  }
                  className="border rounded px-2 py-1 text-sm w-full mt-1"
                />
              </div>
              <ChipInput
                label="Certifications"
                value={edit.trust_signals.certifications}
                onChange={(certs) =>
                  updateEdit({ trust_signals: { ...edit.trust_signals, certifications: certs } })
                }
              />
              <div>
                <label className="text-xs font-medium text-gray-500">Sustainability Notes</label>
                <textarea
                  value={edit.trust_signals.sustainability_notes}
                  onChange={(e) =>
                    updateEdit({
                      trust_signals: { ...edit.trust_signals, sustainability_notes: e.target.value },
                    })
                  }
                  className="border rounded px-2 py-1 text-sm w-full mt-1"
                  rows={2}
                />
              </div>
              <div>
                <div className="flex justify-between">
                  <label className="text-xs font-medium text-gray-500">Agent Summary</label>
                  <span className={`text-xs ${summaryColor}`}>{summaryLen}/240</span>
                </div>
                <textarea
                  value={edit.agent_summary}
                  onChange={(e) => {
                    if (e.target.value.length <= 240) updateEdit({ agent_summary: e.target.value });
                  }}
                  className="border rounded px-2 py-1 text-sm w-full mt-1"
                  rows={3}
                />
              </div>
              <div>
                <p className="text-xs font-medium text-gray-500">
                  Suggested attributes ({edit.suggested_attributes.length})
                </p>
                {edit.suggested_attributes.length === 0 ? (
                  <p className="text-xs text-gray-400 mt-1">No missing attributes suggested</p>
                ) : (
                  <ul className="mt-1 space-y-2" aria-label="Suggested attributes">
                    {edit.suggested_attributes.map((s, i) => (
                      <li key={s.key} className="border rounded p-2 text-xs">
                        <div className="flex items-center gap-2">
                          <span className="font-mono font-medium">{s.key}</span>
                          <span
                            className={`px-1.5 py-0.5 rounded ${
                              s.source === "product_text"
                                ? "bg-blue-100 text-blue-800"
                                : "bg-yellow-100 text-yellow-800"
                            }`}
                          >
                            {s.source === "product_text" ? "from text" : "missing"}
                          </span>
                          <button
                            onClick={() => removeSuggestion(i)}
                            aria-label={`Remove ${s.key}`}
                            className="ml-auto text-gray-400 hover:text-red-600"
                          >
                            ×
                          </button>
                        </div>
                        {s.source === "product_text" && (
                          <input
                            aria-label={`Value for ${s.key}`}
                            value={s.value === null ? "" : String(s.value)}
                            onChange={(e) => updateSuggestionValue(i, e.target.value)}
                            className={`border rounded px-2 py-1 w-full mt-1 ${
                              String(s.value ?? "").trim() === "" ? "border-red-500" : ""
                            }`}
                          />
                        )}
                        {s.reason && <p className="text-gray-500 mt-1">{s.reason}</p>}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <div>
                <span className="text-xs font-medium text-gray-500">Confidence: </span>
                <span
                  className={`text-xs font-bold ${
                    edit.confidence_score >= 0.7 ? "text-green-600" : "text-yellow-600"
                  }`}
                >
                  {edit.confidence_score.toFixed(2)}
                </span>
              </div>
            </div>
          ) : (
            <p className="text-sm text-gray-400">No enrichment data</p>
          )}
        </div>

        {/* Panel 4: History + Comments */}
        <div className="border rounded-lg p-4">
          <div className="flex gap-4 mb-3">
            <button
              onClick={() => setActiveTab("history")}
              className={`text-sm font-medium ${activeTab === "history" ? "text-blue-600 border-b-2 border-blue-600" : "text-gray-500"}`}
            >
              History
            </button>
            <button
              onClick={() => setActiveTab("comments")}
              className={`text-sm font-medium ${activeTab === "comments" ? "text-blue-600 border-b-2 border-blue-600" : "text-gray-500"}`}
            >
              Comments
            </button>
          </div>

          {activeTab === "history" && (
            <div className="space-y-2">
              <div className="space-y-2 max-h-48 overflow-y-auto">
                {versions.map((v) => (
                  <div
                    key={v.version_id}
                    onClick={() => setDiffVersionId(diffVersionId === v.version_id ? null : v.version_id)}
                    className={`border rounded p-2 text-xs cursor-pointer hover:bg-gray-50 ${
                      diffVersionId === v.version_id ? "ring-2 ring-blue-400" : ""
                    }`}
                  >
                    <div className="flex justify-between">
                      <span className="font-medium">
                        {v.generated_by === "llm" ? "LLM" : "Human"}
                      </span>
                      <span className={`px-1.5 py-0.5 rounded text-xs ${
                        v.review_status === "APPROVED" ? "bg-green-100 text-green-800" :
                        v.review_status === "REJECTED" ? "bg-red-100 text-red-800" :
                        "bg-yellow-100 text-yellow-800"
                      }`}>
                        {v.review_status}
                      </span>
                    </div>
                    <p className="text-gray-500 mt-1">{v.agent_summary}</p>
                    <p className="text-gray-400 mt-1">{v.created_at?.slice(0, 19)}</p>
                  </div>
                ))}
                {versions.length === 0 && <p className="text-gray-400">No versions</p>}
              </div>
              {diffVersionId && (() => {
                const selected = versions.find((v) => v.version_id === diffVersionId);
                const latest = versions[0];
                if (!selected || !latest || selected.version_id === latest.version_id) return null;
                const fields = [
                  "use_case_tags",
                  "persona_tags",
                  "agent_summary",
                  "confidence_score",
                  "suggested_attributes",
                ] as const;
                type FieldKey = typeof fields[number];
                const format = (v: VersionEntry, f: FieldKey) => {
                  if (f === "suggested_attributes") {
                    return (v.suggested_attributes ?? [])
                      .map((s) => (s.value === null ? s.key : `${s.key}=${s.value}`))
                      .join(", ");
                  }
                  const val = v[f];
                  return Array.isArray(val) ? val.join(", ") : String(val ?? "");
                };
                return (
                  <div className="border-t pt-2 mt-2">
                    <p className="text-xs font-medium text-gray-500 mb-2">
                      Diff: selected vs latest
                    </p>
                    <div className="grid grid-cols-2 gap-2 text-xs">
                      <div className="font-medium text-gray-400">Selected</div>
                      <div className="font-medium text-gray-400">Latest</div>
                      {fields.map((f) => {
                        const old = format(selected, f);
                        const cur = format(latest, f);
                        const changed = old !== cur;
                        return (
                          <div key={f} className="contents">
                            <div className={changed ? "bg-red-50 p-1 rounded" : "p-1"}>
                              <span className="text-gray-400">{f}: </span>{old}
                            </div>
                            <div className={changed ? "bg-green-50 p-1 rounded" : "p-1"}>
                              <span className="text-gray-400">{f}: </span>{cur}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                );
              })()}
            </div>
          )}

          {activeTab === "comments" && (
            <div className="space-y-3">
              <div className="max-h-60 overflow-y-auto space-y-2">
                {comments.map((c) => (
                  <div key={c.comment_id} className="border rounded p-2 text-xs">
                    <div className="flex justify-between">
                      <span className="font-medium">{c.author_email}</span>
                      <span className="px-1.5 py-0.5 rounded bg-gray-100 text-gray-600">{c.comment_type}</span>
                    </div>
                    <p className="mt-1">{c.body}</p>
                    <p className="text-gray-400 mt-1">{c.created_at?.slice(0, 19)}</p>
                  </div>
                ))}
                {comments.length === 0 && <p className="text-gray-400 text-xs">No comments yet</p>}
              </div>
              {versionId && (
                <div className="border-t pt-2 space-y-2">
                  <select
                    value={commentType}
                    onChange={(e) => setCommentType(e.target.value)}
                    className="border rounded px-2 py-1 text-xs w-full"
                  >
                    <option value="NOTE">Note</option>
                    <option value="PROMPT_FEEDBACK">Prompt Feedback</option>
                    <option value="QUALITY_FLAG">Quality Flag</option>
                  </select>
                  <textarea
                    value={commentBody}
                    onChange={(e) => setCommentBody(e.target.value)}
                    placeholder="Add a comment..."
                    className="border rounded w-full p-2 text-sm"
                    rows={2}
                  />
                  <button
                    onClick={handleComment}
                    disabled={!commentBody.trim()}
                    className="px-3 py-1 text-xs bg-blue-600 text-white rounded disabled:opacity-30"
                  >
                    Post comment
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Action bar */}
      <div className="sticky bottom-0 bg-white border-t mt-6 py-3 flex flex-wrap gap-2">
        <button
          onClick={handleApprove}
          disabled={!versionId}
          className="px-4 py-2 bg-green-600 text-white rounded text-sm disabled:opacity-30 hover:bg-green-700"
        >
          Approve (a)
        </button>
        <button
          onClick={handleApproveWithEdits}
          disabled={!dirty || !versionId || !edit || hasInvalidSuggestion(edit)}
          className="px-4 py-2 bg-green-500 text-white rounded text-sm disabled:opacity-30 hover:bg-green-600"
        >
          Approve with edits
        </button>
        <button
          onClick={() => setRejectModal(true)}
          disabled={!versionId}
          className="px-4 py-2 bg-red-600 text-white rounded text-sm disabled:opacity-30 hover:bg-red-700"
        >
          Reject (r)
        </button>
        <button
          onClick={() => setReenrichModal(true)}
          disabled={!versionId}
          className="px-4 py-2 bg-blue-600 text-white rounded text-sm disabled:opacity-30 hover:bg-blue-700"
        >
          Re-enrich
        </button>
        <button
          onClick={openEscalateModal}
          disabled={!versionId}
          className="px-4 py-2 bg-orange-500 text-white rounded text-sm disabled:opacity-30 hover:bg-orange-600"
        >
          Escalate
        </button>
        <button
          onClick={handleSaveDraft}
          disabled={!dirty}
          className="px-4 py-2 border rounded text-sm disabled:opacity-30"
        >
          Save draft
        </button>
      </div>

      {/* Reject modal */}
      {rejectModal && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 w-96">
            <h3 className="font-semibold mb-2">Reject — Reason Required</h3>
            <textarea
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              placeholder="Min 10 characters..."
              className="border rounded w-full p-2 text-sm"
              rows={3}
            />
            <div className="flex justify-end gap-2 mt-3">
              <button onClick={() => setRejectModal(false)} className="px-3 py-1 text-sm border rounded">
                Cancel
              </button>
              <button
                onClick={handleReject}
                disabled={rejectReason.length < 10}
                className="px-3 py-1 text-sm bg-red-600 text-white rounded disabled:opacity-30"
              >
                Reject
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Re-enrich modal */}
      {reenrichModal && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 w-96">
            <h3 className="font-semibold mb-2">Re-enrich with Feedback</h3>
            <textarea
              value={reenrichFeedback}
              onChange={(e) => setReenrichFeedback(e.target.value)}
              placeholder="Feedback for LLM..."
              className="border rounded w-full p-2 text-sm"
              rows={3}
            />
            <div className="flex justify-end gap-2 mt-3">
              <button onClick={() => setReenrichModal(false)} className="px-3 py-1 text-sm border rounded">
                Cancel
              </button>
              <button onClick={handleReenrich} className="px-3 py-1 text-sm bg-blue-600 text-white rounded">
                Re-enrich
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Escalate modal */}
      {escalateModal && (
        <div className="fixed inset-0 bg-black/30 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 w-96">
            <h3 className="font-semibold mb-2">Escalate to User</h3>
            <select
              value={escalateUserId}
              onChange={(e) => setEscalateUserId(e.target.value)}
              className="border rounded w-full p-2 text-sm mb-2"
            >
              <option value="">Select user...</option>
              {users.map((u) => (
                <option key={u.id} value={u.id}>{u.name} ({u.email})</option>
              ))}
            </select>
            <textarea
              value={escalateReason}
              onChange={(e) => setEscalateReason(e.target.value)}
              placeholder="Reason for escalation..."
              className="border rounded w-full p-2 text-sm"
              rows={3}
            />
            <div className="flex justify-end gap-2 mt-3">
              <button onClick={() => setEscalateModal(false)} className="px-3 py-1 text-sm border rounded">
                Cancel
              </button>
              <button
                onClick={handleEscalate}
                disabled={!escalateUserId || !escalateReason}
                className="px-3 py-1 text-sm bg-orange-500 text-white rounded disabled:opacity-30"
              >
                Escalate
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
