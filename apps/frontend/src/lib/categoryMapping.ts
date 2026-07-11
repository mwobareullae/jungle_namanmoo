const CATEGORY_GROUP_TO_CODES: Record<string, string[]> = {
  스킨케어: ["toner", "serum", "cream", "lotion", "set"],
  클렌징: ["cleanser", "cleansing", "exfoliant"],
  바디케어: ["bodycare", "hair_body"],
  헤어케어: ["haircare"],
  뷰티소품: ["beauty_tool"],
  마스크팩: ["mask", "mask_pack"],
  선케어: ["suncare", "sunscreen"],
  메이크업: ["makeup", "eye_neck", "spot"],
  네일: ["nail"],
  "향수/디퓨저": ["fragrance"]
};

export function getCategoryCodesByGroupTitle(title: string): string[] {
  return CATEGORY_GROUP_TO_CODES[title] ?? [];
}
