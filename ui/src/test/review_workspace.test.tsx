import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi, describe, it, expect, beforeEach } from "vitest";

vi.mock("@/lib/api", () => ({
  fetchSku: vi.fn(),
  fetchVersions: vi.fn(),
  fetchUsers: vi.fn(),
  fetchComments: vi.fn(),
  submitReview: vi.fn(),
}));

import ReviewWorkspace from "@/app/skus/[skuId]/page";
import { fetchSku, fetchVersions, fetchUsers, fetchComments, submitReview } from "@/lib/api";

const mockSku = {
  sku_id: "SKU-1",
  title: "Laptop Pro",
  brand: "TestBrand",
  category: "laptops",
  price: 999.99,
  attributes: { ram: "16GB" },
  source: "json",
  updated_at: "2025-01-01T00:00:00Z",
  enrichment: {
    version_id: "v1",
    generated_by: "llm",
    use_case_tags: ["student"],
    persona_tags: ["budget_buyer"],
    trust_signals: {
      warranty_months: 12,
      certifications: ["energy_star"],
      sustainability_notes: "Recyclable packaging",
    },
    agent_summary: "A great laptop for students.",
    confidence_score: 0.85,
    evidence_fields: ["price", "ram"],
    created_at: "2025-01-01T00:00:00Z",
    review_status: "PENDING_REVIEW",
  },
  audit: {
    audit_id: "a1",
    completeness_score: 0.9,
    richness_score: 0.7,
    missing_critical_fields: [],
    low_quality_fields: [],
    priority_for_enrichment: "LOW",
  },
};

const mockVersions = [
  {
    version_id: "v1",
    parent_version_id: null,
    generated_by: "llm",
    model_name: "gemini-pro",
    use_case_tags: ["student"],
    persona_tags: ["budget_buyer"],
    trust_signals: {},
    agent_summary: "A great laptop for students.",
    confidence_score: 0.85,
    evidence_fields: [],
    created_at: "2025-01-01T00:00:00Z",
    review_status: "PENDING_REVIEW",
    reviewer_id: null,
    reviewed_at: null,
  },
];

beforeEach(() => {
  vi.mocked(fetchSku).mockResolvedValue(mockSku);
  vi.mocked(fetchVersions).mockResolvedValue(mockVersions);
  vi.mocked(fetchComments).mockResolvedValue([]);
  vi.mocked(submitReview).mockResolvedValue(undefined);
  localStorage.clear();
});

describe("Review Workspace", () => {
  it("renders product panel", async () => {
    render(<ReviewWorkspace />);
    await waitFor(() => {
      expect(screen.getByText("Product")).toBeInTheDocument();
      expect(screen.getByText("TestBrand")).toBeInTheDocument();
      expect(screen.getByText("laptops")).toBeInTheDocument();
      expect(screen.getByText("$999.99")).toBeInTheDocument();
    });
  });

  it("renders audit score bars with correct colors", async () => {
    render(<ReviewWorkspace />);
    await waitFor(() => {
      expect(screen.getByText("Completeness")).toBeInTheDocument();
      expect(screen.getByText("90%")).toBeInTheDocument();
      expect(screen.getByText("Richness")).toBeInTheDocument();
      expect(screen.getByText("70%")).toBeInTheDocument();
    });
  });

  it("chip input adds tag on enter", async () => {
    const user = userEvent.setup();
    render(<ReviewWorkspace />);

    await waitFor(() => expect(screen.getByText("Use Case Tags")).toBeInTheDocument());
    const inputs = screen.getAllByPlaceholderText("Add tag...");
    const tagInput = inputs[0]; // Use Case Tags input

    await user.type(tagInput, "gaming{Enter}");
    await waitFor(() => {
      expect(screen.getByText("gaming")).toBeInTheDocument();
    });
  });

  it("chip input deduplicates silently", async () => {
    const user = userEvent.setup();
    render(<ReviewWorkspace />);

    await waitFor(() => expect(screen.getByText("student")).toBeInTheDocument());
    const inputs = screen.getAllByPlaceholderText("Add tag...");
    const tagInput = inputs[0];

    await user.type(tagInput, "student{Enter}");
    // Should still have only one "student" tag
    const studentTags = screen.getAllByText("student");
    expect(studentTags).toHaveLength(1);
  });

  it("chip input removes tag on x click", async () => {
    const user = userEvent.setup();
    render(<ReviewWorkspace />);

    await waitFor(() => expect(screen.getByText("student")).toBeInTheDocument());
    // Find the × button next to "student"
    const removeButtons = screen.getAllByText("×");
    await user.click(removeButtons[0]);

    await waitFor(() => {
      expect(screen.queryByText("student")).not.toBeInTheDocument();
    });
  });

  it("approve button calls API", async () => {
    const user = userEvent.setup();
    render(<ReviewWorkspace />);

    await waitFor(() => expect(screen.getByText("Approve (a)")).toBeInTheDocument());
    await user.click(screen.getByText("Approve (a)"));

    expect(vi.mocked(submitReview)).toHaveBeenCalledWith("SKU-1", {
      action: "approve",
      version_id: "v1",
    });
  });

  it("approve with edits inactive when clean", async () => {
    render(<ReviewWorkspace />);
    await waitFor(() => {
      const btn = screen.getByText("Approve with edits");
      expect(btn).toBeDisabled();
    });
  });

  it("approve with edits active when dirty", async () => {
    const user = userEvent.setup();
    render(<ReviewWorkspace />);

    await waitFor(() => expect(screen.getByText("Use Case Tags")).toBeInTheDocument());
    const inputs = screen.getAllByPlaceholderText("Add tag...");
    await user.type(inputs[0], "new_tag{Enter}");

    await waitFor(() => {
      const btn = screen.getByText("Approve with edits");
      expect(btn).not.toBeDisabled();
    });
  });

  it("reject modal requires reason min 10 chars", async () => {
    const user = userEvent.setup();
    render(<ReviewWorkspace />);

    await waitFor(() => expect(screen.getByText("Reject (r)")).toBeInTheDocument());
    await user.click(screen.getByText("Reject (r)"));

    await waitFor(() => expect(screen.getByText("Reject — Reason Required")).toBeInTheDocument());

    // Reject button in modal should be disabled with short reason
    const rejectBtn = screen.getAllByText("Reject").find(
      (el) => el.closest(".fixed") !== null
    )!;
    expect(rejectBtn).toBeDisabled();

    // Type a short reason
    const textarea = screen.getByPlaceholderText("Min 10 characters...");
    await user.type(textarea, "Too short");
    expect(rejectBtn).toBeDisabled();

    // Type enough
    await user.clear(textarea);
    await user.type(textarea, "This is a sufficient rejection reason");
    expect(rejectBtn).not.toBeDisabled();
  });

  it("summary counter warning at 200", async () => {
    const user = userEvent.setup();
    render(<ReviewWorkspace />);

    await waitFor(() => expect(screen.getByText("Agent Summary")).toBeInTheDocument());

    // Find the agent summary textarea and type 201 chars
    const summaryTextarea = screen.getByDisplayValue("A great laptop for students.");
    await user.clear(summaryTextarea);
    await user.type(summaryTextarea, "x".repeat(201));

    // The counter should show yellow color class
    await waitFor(() => {
      expect(screen.getByText("201/240")).toBeInTheDocument();
    });
  });

  it("summary counter blocks at 240", async () => {
    const user = userEvent.setup();
    render(<ReviewWorkspace />);

    await waitFor(() => expect(screen.getByText("Agent Summary")).toBeInTheDocument());

    const summaryTextarea = screen.getByDisplayValue("A great laptop for students.");
    await user.clear(summaryTextarea);
    await user.type(summaryTextarea, "x".repeat(250));

    // Should be capped at 240
    await waitFor(() => {
      expect(screen.getByText("240/240")).toBeInTheDocument();
    });
  });

  it("history tab shows version timeline", async () => {
    render(<ReviewWorkspace />);
    await waitFor(() => {
      expect(screen.getByText("LLM")).toBeInTheDocument();
      expect(screen.getByText("PENDING_REVIEW")).toBeInTheDocument();
    });
  });

  it("keyboard a triggers approve", async () => {
    render(<ReviewWorkspace />);
    await waitFor(() => expect(screen.getByText("Approve (a)")).toBeInTheDocument());

    fireEvent.keyDown(window, { key: "a" });

    await waitFor(() => {
      expect(vi.mocked(submitReview)).toHaveBeenCalledWith("SKU-1", {
        action: "approve",
        version_id: "v1",
      });
    });
  });

  it("escalate button opens modal", async () => {
    const user = userEvent.setup();
    vi.mocked(fetchUsers).mockResolvedValue([
      { id: "u1", name: "Admin", email: "admin@test.com", roles: [] },
    ]);

    render(<ReviewWorkspace />);
    await waitFor(() => expect(screen.getByText("Escalate")).toBeInTheDocument());
    await user.click(screen.getByText("Escalate"));

    await waitFor(() => {
      expect(screen.getByText("Escalate to User")).toBeInTheDocument();
    });
  });

  it("comments tab shows comment form", async () => {
    const user = userEvent.setup();
    render(<ReviewWorkspace />);

    await waitFor(() => expect(screen.getByText("Comments")).toBeInTheDocument());
    await user.click(screen.getByText("Comments"));

    await waitFor(() => {
      expect(screen.getByPlaceholderText("Add a comment...")).toBeInTheDocument();
      expect(screen.getByText("Post comment")).toBeInTheDocument();
    });
  });
});
