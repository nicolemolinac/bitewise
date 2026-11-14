export function calculateServingTotals(
  liked: Array<{id: string}>,
  weeklyPlan: Array<{slots: Array<{meal?: {id?: string} | null}>}>,
  factor: number,
  dayContexts: Array<{people?: number}>,
  includeUnplannedPicks?: boolean
): Record<string, number>;

export function activeQuickMealReplacements<T>(
  replacements: Record<string, T>,
  liked: Array<{id: string}>,
  weeklyPlan: Array<{slots: Array<{meal?: {id?: string} | null}>}>,
  includeUnplannedPicks?: boolean
): Record<string, T>;
