import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi, describe, it, expect, beforeEach } from "vitest";

const mockUsers = [
  {
    id: "u1",
    name: "Alice Admin",
    email: "alice@test.com",
    active: true,
    roles: [{ role: "ADMIN", category: null }],
  },
  {
    id: "u2",
    name: "Bob Reviewer",
    email: "bob@test.com",
    active: true,
    roles: [{ role: "REVIEWER_CATEGORY", category: "laptops" }],
  },
];

const mockThresholds = {
  completeness_high: 0.6,
  completeness_medium: 0.8,
  richness_high: 0.5,
  richness_medium: 0.7,
};

beforeEach(() => {
  vi.restoreAllMocks();
  global.fetch = vi.fn((url: string | URL | Request) => {
    const urlStr = typeof url === "string" ? url : url.toString();
    if (urlStr.includes("/admin/users")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(mockUsers),
      } as Response);
    }
    if (urlStr.includes("/admin/audit/thresholds")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(mockThresholds),
      } as Response);
    }
    return Promise.resolve({
      ok: true,
      json: () => Promise.resolve({}),
    } as Response);
  });
});

// Import after mocks are set up
import AdminPage from "@/app/admin/page";

describe("Admin Panel", () => {
  it("renders user list table", async () => {
    render(<AdminPage />);
    await waitFor(() => {
      expect(screen.getByText("Alice Admin")).toBeInTheDocument();
      expect(screen.getByText("alice@test.com")).toBeInTheDocument();
      expect(screen.getByText("Bob Reviewer")).toBeInTheDocument();
      expect(screen.getByText("bob@test.com")).toBeInTheDocument();
    });
  });

  it("shows role badges with category", async () => {
    render(<AdminPage />);
    await waitFor(() => {
      expect(screen.getByText(/ADMIN/)).toBeInTheDocument();
      expect(screen.getByText(/REVIEWER_CATEGORY \(laptops\)/)).toBeInTheDocument();
    });
  });

  it("assign role shows form when + role clicked", async () => {
    const user = userEvent.setup();
    render(<AdminPage />);

    await waitFor(() => expect(screen.getAllByText("+ role")).toHaveLength(2));
    await user.click(screen.getAllByText("+ role")[0]);

    await waitFor(() => {
      expect(screen.getByText("Role")).toBeInTheDocument();
      expect(screen.getByText("Assign")).toBeInTheDocument();
    });
  });

  it("category required for REVIEWER_CATEGORY", async () => {
    const user = userEvent.setup();
    render(<AdminPage />);

    await waitFor(() => expect(screen.getAllByText("+ role")).toHaveLength(2));
    await user.click(screen.getAllByText("+ role")[0]);

    // Select REVIEWER_CATEGORY
    const roleSelect = screen.getByDisplayValue("Select...");
    await user.selectOptions(roleSelect, "REVIEWER_CATEGORY");

    // Category input should appear
    await waitFor(() => {
      expect(screen.getByPlaceholderText("e.g. laptops")).toBeInTheDocument();
    });
  });

  it("assign role calls API", async () => {
    const user = userEvent.setup();
    render(<AdminPage />);

    await waitFor(() => expect(screen.getAllByText("+ role")).toHaveLength(2));
    await user.click(screen.getAllByText("+ role")[0]);

    const roleSelect = screen.getByDisplayValue("Select...");
    await user.selectOptions(roleSelect, "REVIEWER_GENERAL");
    await user.click(screen.getByText("Assign"));

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining("/admin/users/u1/roles"),
        expect.objectContaining({ method: "POST" })
      );
    });
  });

  it("SKU reassignment calls API", async () => {
    const user = userEvent.setup();
    render(<AdminPage />);

    await waitFor(() => expect(screen.getByText("SKU Reassignment")).toBeInTheDocument());

    const skuInput = screen.getByLabelText("SKU ID");
    await user.type(skuInput, "SKU-42");

    const userSelect = screen.getAllByDisplayValue("Select user...")[0];
    await user.selectOptions(userSelect, "u1");

    await user.click(screen.getByText("Reassign"));

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining("/admin/assignments/SKU-42"),
        expect.objectContaining({ method: "PUT" })
      );
    });
  });

  it("threshold save requires confirmation modal", async () => {
    const user = userEvent.setup();
    render(<AdminPage />);

    await waitFor(() => expect(screen.getByText("Save Thresholds")).toBeInTheDocument());
    await user.click(screen.getByText("Save Thresholds"));

    await waitFor(() => {
      expect(screen.getByText("Confirm Threshold Update")).toBeInTheDocument();
      expect(screen.getByText("Confirm")).toBeInTheDocument();
      expect(screen.getByText("Cancel")).toBeInTheDocument();
    });
  });

  it("threshold confirm calls API", async () => {
    const user = userEvent.setup();
    render(<AdminPage />);

    await waitFor(() => expect(screen.getByText("Save Thresholds")).toBeInTheDocument());
    await user.click(screen.getByText("Save Thresholds"));

    await waitFor(() => expect(screen.getByText("Confirm")).toBeInTheDocument());
    await user.click(screen.getByText("Confirm"));

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining("/admin/audit/thresholds"),
        expect.objectContaining({ method: "PUT" })
      );
    });
  });
});
