/**
 * Normalize shopping servings without rounding away a user's fractional portion.
 * Invalid, non-finite or non-positive values fall back to one serving.
 */
export function preserveFractionalServings(servings) {
  if (!servings || typeof servings !== "object" || Array.isArray(servings)) return {};
  return Object.fromEntries(
    Object.entries(servings).map(([mealId, rawValue]) => {
      const quantity = Number(rawValue);
      return [mealId, Number.isFinite(quantity) && quantity > 0 ? quantity : 1];
    }),
  );
}
