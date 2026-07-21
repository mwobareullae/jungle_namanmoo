import { describe, expect, it } from "vitest";
import { categoryMenu, resolveCategoryMenuRoute } from "./categoryMenu";

describe("categoryMenu", () => {
  it("renders the fixed top-level menu in the agreed order", () => {
    expect(categoryMenu.map(({ slug, name }) => ({ slug, name }))).toEqual([
      { slug: "skincare", name: "스킨케어" },
      { slug: "focus-care", name: "집중케어" },
      { slug: "makeup", name: "메이크업" },
      { slug: "body-hair", name: "바디·헤어" },
      { slug: "men", name: "남성" },
      { slug: "cleansing", name: "클렌징" },
      { slug: "suncare", name: "선케어" },
      { slug: "fragrance", name: "향수" },
      { slug: "beauty-tools-nail", name: "뷰티소품" },
    ]);
  });

  it.each([
    ["skincare", ["toner", "serum", "cream", "lotion", "set", "mask", "mask_pack"]],
    ["focus-care", ["eye_neck", "spot", "exfoliant"]],
    ["makeup", ["makeup"]],
    ["body-hair", ["bodycare", "haircare"]],
    ["men", ["men_allinone"]],
    ["cleansing", ["cleanser", "cleansing"]],
    ["suncare", ["suncare", "sunscreen"]],
    ["fragrance", ["fragrance"]],
    ["beauty-tools-nail", ["beauty_tool", "nail"]],
  ])("resolves the %s group route to product codes", (groupSlug, productCodes) => {
    expect(resolveCategoryMenuRoute(groupSlug, null)?.productCodes).toEqual(productCodes);
  });

  it.each([
    ["skincare", "toner", ["toner"]],
    ["skincare", "serum", ["serum"]],
    ["skincare", "cream", ["cream"]],
    ["skincare", "lotion", ["lotion"]],
    ["skincare", "set", ["set"]],
    ["skincare", "mask-pack", ["mask", "mask_pack"]],
    ["focus-care", "eye-neck-care", ["eye_neck"]],
    ["focus-care", "trouble-care", ["spot"]],
    ["focus-care", "exfoliant", ["exfoliant"]],
    ["makeup", "makeup", ["makeup"]],
    ["body-hair", "bodycare", ["bodycare"]],
    ["body-hair", "haircare", ["haircare"]],
    ["men", "men-allinone", ["men_allinone"]],
    ["cleansing", "cleanser", ["cleanser"]],
    ["cleansing", "cleansing", ["cleansing"]],
    ["suncare", "suncare", ["suncare"]],
    ["suncare", "sunscreen", ["sunscreen"]],
    ["fragrance", "fragrance", ["fragrance"]],
    ["beauty-tools-nail", "beauty-tools", ["beauty_tool"]],
    ["beauty-tools-nail", "nail", ["nail"]],
  ])("resolves /category/%s?subcategory=%s to product codes", (groupSlug, subcategorySlug, productCodes) => {
    expect(resolveCategoryMenuRoute(groupSlug, subcategorySlug)?.productCodes).toEqual(productCodes);
  });

  it("does not expose the retained hair_body product code in the customer menu", () => {
    expect(categoryMenu.some((group) => group.productCodes.includes("hair_body"))).toBe(false);
    expect(resolveCategoryMenuRoute("hair_body", null)).toBeNull();
  });

  it.each([
    ["mask_pack", "mask"],
    ["bodycare", null],
  ])("treats the legacy route /category/%s as invalid", (groupSlug, subcategorySlug) => {
    expect(resolveCategoryMenuRoute(groupSlug, subcategorySlug)).toBeNull();
  });
});
