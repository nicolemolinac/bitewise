# Bitewise product intelligence and recommendation architecture

## Product principle
Bitewise is a personal food decision engine, not a recipe generator with a supermarket lookup bolted on. Every feature should reuse one consistent catalog and one consistent understanding of meals, products, cost, nutrition, convenience and the user's feedback.

## Data boundaries
- `products`: provider identity, name, category, pack size, pack checkout price, reference/unit price, URL, image URL and catalog freshness. The image pipeline remains independent.
- `product_intelligence`: derived culinary classification (ingredient vs prepared component vs complete meal), culinary role, dish families, preparation/storage state, convenience level, confidence, evidence and classifier version. Recomputable; never overwrite source product facts.
- Future `product_details`: separately sourced product-page facts (EAN, ingredient statement, allergens and per-100g nutrition). Missing values stay null; every field needs provenance and fetch status. This is not part of the image scraper.
- `recipe_history`: canonical generated/saved recipes and lifecycle state.
- `events`: behavioral feedback. Recommendation features are derived from feedback and recipe content; no model training or extra LLM call is needed for every request.
- `pantry`, `shopping_state`, `plans`: user state used by recipe ranking and basket optimization.

## Recommendation pipeline
1. Parse a request into explicit constraints (dish/cuisine, meal type, time, effort, budget, nutrition, equipment, servings).
2. Retrieve candidates from saved recipes and the REWE catalog using indexed deterministic filters.
3. Expand or create a recipe only when the user asks for a recipe that does not already exist. Gemini receives compact catalog concepts, never the SKU table.
4. Rank candidates using a hybrid score: hard-constraint eligibility first, then learned taste signals, variety/recency, pantry coverage, estimated checkout cost, consumed cost, waste, effort and preparation fit.
5. Explain the top recommendation and offer genuinely different alternatives: homemade, shortcut/hybrid and complete ready meal only when a real catalog equivalent exists.
6. Reuse the same normalized recipe/product records for nutrition, shopping, planning, pantry and cooking.

## Learning strategy
Start with a transparent contextual recommender. Likes, skips, dislikes, cooked/eaten events and repeat behavior update preference weights over cuisine and recipe tags. Use recency decay and diversity so one historic click does not dominate forever. With one personal user and sparse feedback, a small interpretable model is safer and more useful than training a neural network. Later, if interaction volume supports it, evaluate a lightweight ranking model offline against a held-out history and keep a deterministic fallback.

## Cost and correctness rules
- Never confuse pack checkout price with price per kg/litre.
- Keep checkout spend separate from the portion of pack cost consumed by a recipe.
- Pantry quantities only cover ingredients when units are compatible.
- Unknown stock is not in-stock.
- Nutrition is calculated from verified per-100g/per-100ml product facts and recipe quantities; never infer missing nutrition.
- A passata jar is a sauce component, not a ready-made pasta meal. Cooked chicken strips are a protein shortcut, not a full meal. Dried pasta is an ingredient. A lasagne tray can be a complete meal.

## Operational safety
Product classification is an offline/recomputable process. It does not launch REWE requests, alter product images or share browser/CDP state with image scraping. New catalog rows can be marked pending and classified in bounded batches. No catalog backfill is run automatically during API startup.
