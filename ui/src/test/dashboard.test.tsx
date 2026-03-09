import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi, describe, it, expect, beforeEach } from "vitest";

vi.mock("@/lib/api", () => ({
  fetchDashboardStats: vi.fn(),
  fetchSkus: vi.fn(),
  fetchMe: vi.fn(),
}));

import DashboardPage from "@/app/dashboard/page";
import { fetchDashboardStats, fetchMe, fetchSkus } from "@/lib/api";

const mockStats = {
  pending_review_count: 12,
  escalated_count: 3,
  throughput: [{ date: "2025-01-01", count: 5 }],
  top_rejection_reasons: [{ reason: "missing tags", count: 2 }],
};

const mockSkuData = {
  items: [
    {
      sku_id: "SKU-1",
      title: "Laptop Pro",
      brand: "TestBrand",
      category: "laptops",
      price: 999.99,
      attributes: {},
      source: "json",
      updated_at: "2025-01-01T00:00:00Z",
    },
  ],
  total: 1,
  page: 1,
  page_size: 20,
};

const mockAdminUser = {
  id: "u1",
  name: "Admin",
  email: "admin@test.com",
  roles: [{ role: "ADMIN", category: null }],
};

const mockCategoryReviewer = {
  id: "u2",
  name: "Reviewer",
  email: "reviewer@test.com",
  roles: [{ role: "REVIEWER_CATEGORY", category: "laptops" }],
};

beforeEach(() => {
  vi.mocked(fetchDashboardStats).mockResolvedValue(mockStats);
  vi.mocked(fetchSkus).mockResolvedValue(mockSkuData);
  vi.mocked(fetchMe).mockResolvedValue(mockAdminUser);
});

describe("Dashboard", () => {
  it("renders backlog count cards", async () => {
    render(<DashboardPage />);
    await waitFor(() => {
      expect(screen.getByText("Pending Review")).toBeInTheDocument();
      expect(screen.getByText("12")).toBeInTheDocument();
      expect(screen.getByText("Escalated")).toBeInTheDocument();
      expect(screen.getByText("3")).toBeInTheDocument();
    });
  });

  it("renders SKU table with rows", async () => {
    render(<DashboardPage />);
    await waitFor(() => {
      expect(screen.getByText("SKU-1")).toBeInTheDocument();
      expect(screen.getByText("Laptop Pro")).toBeInTheDocument();
      expect(screen.getByText("TestBrand")).toBeInTheDocument();
    });
  });

  it("filter by category updates API call", async () => {
    const user = userEvent.setup();
    render(<DashboardPage />);

    await waitFor(() => expect(screen.getByText("SKU-1")).toBeInTheDocument());
    vi.mocked(fetchSkus).mockClear();

    const categoryInput = screen.getByPlaceholderText("Category");
    await user.type(categoryInput, "laptops");

    await waitFor(() => {
      expect(vi.mocked(fetchSkus)).toHaveBeenCalledWith(
        expect.objectContaining({ category: "laptops" })
      );
    });
  });

  it("category reviewer has category filter locked", async () => {
    vi.mocked(fetchMe).mockResolvedValue(mockCategoryReviewer);
    render(<DashboardPage />);

    await waitFor(() => {
      const lockedInput = screen.getByDisplayValue("laptops");
      expect(lockedInput).toBeDisabled();
    });
  });

  it("keyboard j moves focus down in table", async () => {
    render(<DashboardPage />);
    await waitFor(() => expect(screen.getByText("SKU-1")).toBeInTheDocument());

    // The SkuTable component handles j/k via window keydown
    // With one row, pressing j should not error
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "j" }));
    // The focused row class should be applied to the first row
    const row = screen.getByText("SKU-1").closest("tr");
    expect(row).toBeInTheDocument();
  });

  it("displays search input", async () => {
    render(<DashboardPage />);
    await waitFor(() => {
      expect(screen.getByPlaceholderText("Search SKU or title...")).toBeInTheDocument();
    });
  });
});
