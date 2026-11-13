# Bitewise Ingredient Intelligence

## Design

Recipe generation still makes one Gemini request. That same response now includes a private
`ingredient_intelligence` object for each ingredient alongside the normal recipe fields.
The user-facing recipe remains unchanged. The metadata is saved with recipe history and includes
canonical identity, EN/DE/ES names, retail aliases, product form, culinary role, unit dimension
and AI-proposed substitutions.

Shopping-time work is local and deterministic:

1. Validate ingredient units and preserve requested product forms.
2. Retrieve REWE candidates using multilingual recipe metadata and catalog title/category fields.
3. Prefer confirmed exact matches, then curated/AI-approved substitutions.
4. AI-proposed substitutions are review-only. Same-form, curated high-confidence equivalences
   (such as neutral vegetable oil to rapeseed oil) can be costed automatically when no exact
   product exists. Cross-form alternatives (such as frozen fries to fresh potatoes) always need
   explicit user confirmation and recipe-step adaptation.
5. If lexical retrieval has no confident match, use local multilingual embeddings to suggest
   possible products. Semantic suggestions are review-only: they are not costed or added to REWE
   until the user explicitly chooses one.
6. A confirmed choice is persisted through the existing product override mechanism. Saved recipes are
   then reconciled locally so their ingredient list, cooking steps, product matches and costs stay in sync.

## Local semantic index

The semantic layer uses FastEmbed with `intfloat/multilingual-e5-small` on CPU/ONNX. It does
not call Gemini or any paid embedding API.

Install the updated backend requirements:

```bash
cd ~/proyectos/bitewise/backend
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Build or incrementally update the REWE product index:

```bash
python index_rewe_semantics.py
```

The first run downloads the embedding model into `backend/data/models/fastembed`. Product vectors
are persisted in the database table `product_semantic_embeddings`; unchanged products are skipped
on later runs. After the first index has been created, successful REWE catalog refreshes incrementally
update changed/new products and remove stale vectors. The model files are local runtime data and are excluded from Git.

If the index has not been built, Bitewise continues using multilingual lexical retrieval. If local
semantic inference is unavailable, it falls back to lexical matching without failing the basket.

## QA

```bash
python qa_ingredient_intelligence.py
python qa_ingredient_costing.py
python qa_recipe_history.py
python qa_semantic_catalog.py
```

The focused QA covers multilingual names, missing AI metadata fallbacks, form conflicts (for example canned vs frozen corn, fresh vs frozen potatoes, and soft tortillas vs tortilla chips), safe substitutions, unit validation, and the rule that semantic suggestions require explicit user confirmation before they affect the basket total. `qa_recipe_history.py` also exercises a saved-recipe reconciliation: selecting fresh potatoes updates the recipe ingredients and cooking steps, persists the change, and does not duplicate the preparation instruction on a second run. `qa_semantic_catalog.py` tests indexing, incremental updates, retrieval, form filtering, and stale-vector cleanup with a fake local embedding model; it does not download a model or call a paid API.
