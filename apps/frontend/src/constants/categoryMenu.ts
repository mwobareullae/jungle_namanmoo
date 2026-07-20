export type CategoryMenuItem = {
  slug: string;
  name: string;
  productCodes: readonly string[];
};

export type CategoryMenuGroup = {
  slug: string;
  name: string;
  productCodes: readonly string[];
  items: readonly CategoryMenuItem[];
};

export type ResolvedCategoryMenuRoute = {
  group: CategoryMenuGroup;
  item: CategoryMenuItem | null;
  productCodes: readonly string[];
};

export const categoryMenu: readonly CategoryMenuGroup[] = [
  {
    slug: "skincare",
    name: "스킨케어",
    productCodes: ["toner", "serum", "cream", "lotion", "set", "mask", "mask_pack"],
    items: [
      { slug: "toner", name: "토너", productCodes: ["toner"] },
      { slug: "serum", name: "세럼", productCodes: ["serum"] },
      { slug: "cream", name: "크림", productCodes: ["cream"] },
      { slug: "lotion", name: "로션", productCodes: ["lotion"] },
      { slug: "set", name: "세트", productCodes: ["set"] },
      { slug: "mask-pack", name: "마스크팩", productCodes: ["mask", "mask_pack"] },
    ],
  },
  {
    slug: "focus-care",
    name: "집중케어",
    productCodes: ["eye_neck", "spot", "exfoliant"],
    items: [
      { slug: "eye-neck-care", name: "아이·넥 케어", productCodes: ["eye_neck"] },
      { slug: "trouble-care", name: "트러블 케어", productCodes: ["spot"] },
      { slug: "exfoliant", name: "각질 케어", productCodes: ["exfoliant"] },
    ],
  },
  {
    slug: "makeup",
    name: "메이크업",
    productCodes: ["makeup"],
    items: [
      { slug: "makeup", name: "메이크업", productCodes: ["makeup"] },
    ],
  },
  {
    slug: "body-hair",
    name: "바디·헤어",
    productCodes: ["bodycare", "haircare"],
    items: [
      { slug: "bodycare", name: "바디케어", productCodes: ["bodycare"] },
      { slug: "haircare", name: "헤어케어", productCodes: ["haircare"] },
    ],
  },
  {
    slug: "men",
    name: "남성",
    productCodes: ["men_allinone"],
    items: [
      { slug: "men-allinone", name: "남성 올인원", productCodes: ["men_allinone"] },
    ],
  },
  {
    slug: "cleansing",
    name: "클렌징",
    productCodes: ["cleanser", "cleansing"],
    items: [
      { slug: "cleanser", name: "클렌저", productCodes: ["cleanser"] },
      { slug: "cleansing", name: "클렌징", productCodes: ["cleansing"] },
    ],
  },
  {
    slug: "suncare",
    name: "선케어",
    productCodes: ["suncare", "sunscreen"],
    items: [
      { slug: "suncare", name: "선케어", productCodes: ["suncare"] },
      { slug: "sunscreen", name: "선크림", productCodes: ["sunscreen"] },
    ],
  },
  {
    slug: "fragrance",
    name: "향수",
    productCodes: ["fragrance"],
    items: [
      { slug: "fragrance", name: "향수·디퓨저", productCodes: ["fragrance"] },
    ],
  },
  {
    slug: "beauty-tools-nail",
    name: "뷰티소품, 네일",
    productCodes: ["beauty_tool", "nail"],
    items: [
      { slug: "beauty-tools", name: "뷰티 도구", productCodes: ["beauty_tool"] },
      { slug: "nail", name: "네일", productCodes: ["nail"] },
    ],
  },
];

export const resolveCategoryMenuRoute = (
  groupSlug: string,
  subcategorySlug: string | null,
): ResolvedCategoryMenuRoute | null => {
  const group = categoryMenu.find((candidate) => candidate.slug === groupSlug);
  if (!group) return null;

  if (!subcategorySlug) {
    return { group, item: null, productCodes: group.productCodes };
  }

  const item = group.items.find((candidate) => candidate.slug === subcategorySlug);
  if (!item) return null;

  return { group, item, productCodes: item.productCodes };
};

export const getCategoryMenuPath = (groupSlug: string, subcategorySlug?: string) => {
  const groupPath = `/category/${encodeURIComponent(groupSlug)}`;
  return subcategorySlug
    ? `${groupPath}?subcategory=${encodeURIComponent(subcategorySlug)}`
    : groupPath;
};
