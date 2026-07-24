const PRESERVE_EXACT_VALUE_COLUMNS = new Set(["normalized_source_name"]);

export const readIngredientMappingCsvCell = (
  cells: Array<string | null | undefined>,
  columnIndex: number,
  columnName: string
): string => {
  const rawValue = String(cells[columnIndex] ?? "");
  return PRESERVE_EXACT_VALUE_COLUMNS.has(columnName) ? rawValue : rawValue.trim();
};
