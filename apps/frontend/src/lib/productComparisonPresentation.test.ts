import { describe, expect, it } from "vitest";
import { getSimilarityReasonLabels } from "./productComparisonPresentation";

describe("productComparisonPresentation", () => {
  it("keeps only the similarity reasons that have customer-facing labels", () => {
    expect(getSimilarityReasonLabels([
      "same_category",
      "shared_ingredients",
      "unknown",
      "similar_price",
    ])).toEqual(["같은 카테고리", "핵심 성분 유사", "가격대 비슷"]);
  });
});
