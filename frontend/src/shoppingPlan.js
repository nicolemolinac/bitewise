export function calculateServingTotals(liked, weeklyPlan, factor, dayContexts, includeUnplannedPicks = false) {
  const totals = {};
  weeklyPlan.forEach((day, index) => {
    (day.slots || []).forEach(slot => {
      if (!slot.meal?.id) return;
      const mealId = slot.meal.id;
      totals[mealId] = (totals[mealId] || 0) + factor * (dayContexts[index]?.people || 1);
    });
  });
  if (includeUnplannedPicks) {
    liked.forEach(meal => {
      if (meal?.id && !totals[meal.id]) totals[meal.id] = factor;
    });
  }
  return totals;
}

export function activeQuickMealReplacements(replacements, liked, weeklyPlan, includeUnplannedPicks = false) {
  const likedIds = new Set(liked.map(meal => meal.id));
  const plannedIds = new Set(
    weeklyPlan.flatMap(day => (day.slots || []).map(slot => slot.meal?.id).filter(Boolean))
  );
  return Object.fromEntries(
    Object.entries(replacements)
      .filter(([mealId]) => likedIds.has(mealId) && (includeUnplannedPicks || plannedIds.has(mealId)))
      .map(([mealId, replacement]) => {
        const occurrences = weeklyPlan.reduce(
          (count, day) => count + (day.slots || []).filter(slot => slot.meal?.id === mealId).length,
          0
        );
        // Keep shortcut quantities synchronized with the live plan. An
        // unplanned pick included explicitly contributes one pick.
        return [mealId, {...replacement, weeklyQuantity: occurrences || 1}];
      })
  );
}
