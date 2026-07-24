import { describe, expect, it } from "vitest";
import type { ProductDetail } from "../types/recommendation";
import { getComparisonHighlightProductIds } from "./ProductComparisonPanel";

const createProduct = (
  productId: string,
  { price, reviewCount }: { price: number | null; reviewCount?: number }
) =>
  ({
    product_id: productId,
    lowest_price: price,
    review_summary: reviewCount === undefined ? undefined : { review_count: reviewCount }
  }) as ProductDetail;

describe("getComparisonHighlightProductIds", () => {
  it("excludes the current product and marks each qualifying comparison product", () => {
    const highlights = getComparisonHighlightProductIds([
      createProduct("current", { price: 1, reviewCount: 100 }),
      createProduct("candidate-1", { price: 100, reviewCount: 2 }),
      createProduct("candidate-2", { price: 200, reviewCount: 5 })
    ]);

    expect([...highlights.lowestPriceProductIds]).toEqual(["candidate-1"]);
    expect([...highlights.mostReviewedProductIds]).toEqual(["candidate-2"]);
    expect(highlights.lowestPriceProductIds.has("current")).toBe(false);
    expect(highlights.mostReviewedProductIds.has("current")).toBe(false);
  });

  it("marks every comparison product when prices and review counts are tied", () => {
    const highlights = getComparisonHighlightProductIds([
      createProduct("current", { price: 50, reviewCount: 10 }),
      createProduct("candidate-1", { price: 100, reviewCount: 4 }),
      createProduct("candidate-2", { price: 100, reviewCount: 4 })
    ]);

    expect([...highlights.lowestPriceProductIds]).toEqual(["candidate-1", "candidate-2"]);
    expect([...highlights.mostReviewedProductIds]).toEqual(["candidate-1", "candidate-2"]);
  });

  it("does not mark a review leader when both comparison products have no reviews", () => {
    const highlights = getComparisonHighlightProductIds([
      createProduct("current", { price: 50, reviewCount: 10 }),
      createProduct("candidate-1", { price: 100, reviewCount: 0 }),
      createProduct("candidate-2", { price: 200, reviewCount: undefined })
    ]);

    expect([...highlights.mostReviewedProductIds]).toEqual([]);
  });

  it("excludes products without a price from the lowest-price comparison", () => {
    const highlights = getComparisonHighlightProductIds([
      createProduct("current", { price: 50, reviewCount: 10 }),
      createProduct("candidate-1", { price: null, reviewCount: 1 }),
      createProduct("candidate-2", { price: 200, reviewCount: 2 })
    ]);

    expect([...highlights.lowestPriceProductIds]).toEqual(["candidate-2"]);
  });

  it("does not mark comparison highlights until both comparison products are ready", () => {
    const highlights = getComparisonHighlightProductIds([
      createProduct("current", { price: 50, reviewCount: 10 }),
      createProduct("candidate-1", { price: 100, reviewCount: 2 })
    ]);

    expect([...highlights.lowestPriceProductIds]).toEqual([]);
    expect([...highlights.mostReviewedProductIds]).toEqual([]);
  });
});
