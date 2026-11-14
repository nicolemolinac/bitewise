import assert from "node:assert/strict";
import test from "node:test";
import { activeQuickMealReplacements, calculateServingTotals } from "../src/shoppingPlan.js";

const liked = [{id:"planned"}, {id:"unplanned-a"}, {id:"unplanned-b"}];
const weeklyPlan = [
  {slots:[{meal:{id:"planned"}}, {meal:{id:"planned"}}]},
  {slots:[]},
];

test("include unplanned picks even when other recipes are already planned", () => {
  assert.deepEqual(
    calculateServingTotals(liked, weeklyPlan, 1, [{people:2}], true),
    {planned:4, "unplanned-a":1, "unplanned-b":1},
  );
});

test("exclude unplanned picks when the basket option is off", () => {
  assert.deepEqual(
    calculateServingTotals(liked, weeklyPlan, 1, [{people:2}], false),
    {planned:4},
  );
});

test("stale shortcut replacements are excluded after a recipe is unplanned", () => {
  const replacements = {
    planned: {label:"planned shortcut"},
    "unplanned-a": {label:"stale shortcut"},
    removed: {label:"removed recipe shortcut"},
  };
  assert.deepEqual(
    activeQuickMealReplacements(replacements, liked, weeklyPlan, false),
    {planned: {label:"planned shortcut", weeklyQuantity:2}},
  );
});

test("unplanned shortcuts are included only when explicitly requested", () => {
  const replacements = {
    planned: {label:"planned shortcut", weeklyQuantity:1},
    "unplanned-a": {label:"unplanned shortcut", weeklyQuantity:4},
  };
  assert.deepEqual(
    activeQuickMealReplacements(replacements, liked, weeklyPlan, true),
    {
      planned: {label:"planned shortcut", weeklyQuantity:2},
      "unplanned-a": {label:"unplanned shortcut", weeklyQuantity:1},
    },
  );
});

test("planned shortcut quantity follows the current number of calendar occurrences", () => {
  const replacements = {planned: {label:"shortcut", weeklyQuantity:1}};
  assert.deepEqual(
    activeQuickMealReplacements(replacements, liked, weeklyPlan, false),
    {planned: {label:"shortcut", weeklyQuantity:2}},
  );
});
