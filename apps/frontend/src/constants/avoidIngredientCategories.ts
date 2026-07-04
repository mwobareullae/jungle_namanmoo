export const avoidIngredientCategories = [
  {
    id: "preservatives",
    label: "보존제/방부제",
    mappedIngredients: [
      "페녹시에탄올",
      "파라벤",
      "이미다졸리디닐우레아",
      "디아졸리디닐우레아",
      "트리클로산",
      "소르빈산"
    ]
  },
  {
    id: "humectant_solvent_helpers",
    label: "무거운 사용감",
    mappedIngredients: ["프로필렌글라이콜", "프로필렌글리콜", "폴리에틸렌글리콜", "PEG 계열"]
  },
  {
    id: "fragrance",
    label: "향료/인공향",
    mappedIngredients: ["향료", "인공 향료", "합성착향료"]
  },
  {
    id: "colorant",
    label: "색소/착색제",
    mappedIngredients: ["합성착색료"]
  },
  {
    id: "none",
    label: "해당없음",
    mappedIngredients: []
  }
] as const;
