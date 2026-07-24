import { describe, expect, it } from "vitest";

import { readIngredientMappingCsvCell } from "./ingredientMappingCsvParser";

describe("readIngredientMappingCsvCell", () => {
  it("normalized_source_name의 U+FEFF와 앞뒤 문자를 그대로 보존한다", () => {
    expect(readIngredientMappingCsvCell(["\ufeff\ufeffwater"], 0, "normalized_source_name")).toBe(
      "\ufeff\ufeffwater"
    );
    expect(readIngredientMappingCsvCell(["향료\ufeff"], 0, "normalized_source_name")).toBe("향료\ufeff");
  });

  it("다른 CSV 컬럼은 기존처럼 앞뒤 공백을 정리한다", () => {
    expect(readIngredientMappingCsvCell(["  CREATE_AND_MAP  "], 0, "action")).toBe("CREATE_AND_MAP");
    expect(readIngredientMappingCsvCell(["  ing_pending_a  "], 0, "pending_code")).toBe("ing_pending_a");
  });
});
