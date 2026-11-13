# Bitewise Ingredient Intelligence

## Design

Recipe generation still makes one Gemini request. That same response now includes a private
`ingredient_intelligence` object for each ingredient alongside the normal recipe fields.
The user-facing recipe remains unchanged. The metadata is saved with recipe history and includes
canonical identity, EN/DE/ES names, retail aliases, product form, culinary role, unit dimension
and explicitly allowed substitutions.

Shopping-time work is local and deterministic:

1. Validate ingredient units and preserve requested product forms.
2. Retrieve REWE candidates using multilingual recipe metadata and catalog title/category fields.
3. Prefer confirmed exact matches, then curated/AI-approved substitutions.
4. If lexical retrieval has no confident match, use local multilingual embeddings to suggest
   possible products. Semantic suggestions are review-only: they are not costed or added to REWE
   until the user explicitly chooses one.
5. A confirmed choice is persisted through the existing product override mechanism.

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
on later runs. Run the indexer again after refreshing the REWE catalog to embed new or changed
products. The model files are local runtime data and are excluded from Git.

If the index has not been built, Bitewise continues using multilingual lexical retrieval. If local
semantic inference is unavailable, it falls back to lexical matching without failing the basket.

## QA

```bash
python qa_ingredient_intelligence.py
python qa_ingredient_costing.py
```

The focused QA covers multilingual names, form conflicts (for example canned vs frozen corn and
soft tortillas vs tortilla chips), safe substitutions, unit validation, and the rule that semantic
suggestions require explicit user confirmation before they affect the basket total.
