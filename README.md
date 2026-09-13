# AttEx — Flexible Attribute Extraction from Criminal Court Decisions

Companion code and data for the paper:

> **Unlocking Criminal Court Decisions: Flexible Information Extraction for Empirical Legal Research**
> Tomáš Knap, Ivana Kvapilíková, Jan Černý, Klára Bendová, Jaromír Šavelka, Vojtěch Pour, Jakub Drápal
> JURIX 2026 — 39th International Conference on Legal Knowledge and Information Systems

Criminal verdicts describe criminal behaviour in free text. Turning those descriptions into
data a legal researcher can analyse requires an attribute set and extraction rules that
cannot be fully specified in advance. **AttEx** is a pipeline that develops both *through*
corpus exploration, with a human-readable annotation manual as the shared specification for
human annotators and for the LLM.

**Project page:** <https://tomasjknap.github.io/attex-pipeline/>

## Pipeline

The pipeline has three LLM stages, driven by one annotation manual (= extraction schema).
Stage numbers match Figure 2 in the paper.

| # | Stage | Script | In → Out |
|---|-------|--------|----------|
| 1 | **Attribute exploration** — induces a schema from the corpus in fixed-size batches, proposing candidate attributes from residual information | `src/a_attribute_explorer.py` | factual statements + initial attributes → attribute schema |
| 2 | **Span extraction** — locates supporting evidence, aligns it with the source and wraps it in `<span id="s1">…</span>` tags | `src/d_dataset_builder.py` | factual statements + schema → spans + values |
| 3 | **Value normalization** — derives value types, formats, normalization rules and category sets from observed values | `src/c_semantic_normalizer.py` | spans + schema → enriched schema |
|   | *Format validation* — checks a built dataset against declared variable constraints | `src/e_format_validator.py` | dataset + constraints → violation report |

Stages 2 and 3 are iterated: the researcher inspects extracted values and supporting spans,
revises the manual, and the accepted manual regenerates annotations across the corpus
(revision cycle B in Figure 2).

## Install

Requires Python 3.13 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

`uv sync` installs the project itself, so the stage scripts and `lib.*` are importable
from anywhere in the environment. `make install`, `make format` and `make check` wrap the
install and the ruff formatting check.

## API keys

The LLM client reads the key for the selected provider from the environment:

| `--provider` | Environment variable |
|--------------|----------------------|
| `openai`     | `OPENAI_API_KEY`     |
| `genai`      | `GENAI_API_KEY`      |
| `groq`       | `GROQ_API_KEY`       |
| `ufalai`     | `UFAL_API_KEY`       |

## Quick start

**1 — Induce an attribute schema** from the DUI development sample:

```bash
uv run src/a_attribute_explorer.py \
  --input data/dui_dev_sample.csv \
  --output dui_schema_induced.json \
  --initial-attributes data/initial_attributes.json \
  --provider openai --model gpt-5.6-terra --temperature 1.0 --reasoning none \
  --parallel-batch-size 10 \
  --schema-update-batch-size 100 \
  --population-threshold 0.85
```

`--schema-update-batch-size` is the induction batch size *N* studied in Section 6.1:
smaller batches yield more granular, often case-specific attributes.

**2 — Extract spans and values** for a fixed schema:

```bash
uv run src/d_dataset_builder.py \
  --input data/dui_test_set.csv \
  --attribute-schema data/dui_attribute_schema.json \
  --output dui_extracted.csv \
  --provider openai --model gpt-5.6-terra \
  --method extract_spans_and_values \
  --batch-size 10 \
  --checkpoint-path .checkpoints/dui
```

`--method` selects a prompt template from `config/prompt_templates/`
(`extract_spans_and_values`, `extract_spans_and_values_per_attribute`,
`copy_spans_and_extract_values`). Long runs are resumable via `--checkpoint-path`.

**3 — Classify normalization strategy** per attribute from the observed values:

```bash
uv run src/c_semantic_normalizer.py \
  --input data/ddb_spans_and_values.csv \
  --attribute-schema data/ddb_attribute_schema.json \
  --output ddb_schema_normalized.json \
  --provider openai --model gpt-5.6-terra \
  --max-sampled-values 50 \
  --single-cardinality-threshold 0.9
```

Each attribute is labelled `standardizable_by_category`, `standardizable_by_format`,
`split_into_multiple_attributes` or `not_standardizable`.

**4 — Validate** a built dataset against the declared constraints:

```bash
uv run src/e_format_validator.py dui_extracted.csv \
  --constraints config/dataset_variable_constraints/vars/SK \
  --variable dateOfOffense \
  --report violations.jsonl
```

## Repository layout

```
src/           pipeline stages (a, c, d, e) and the shared lib/ package
  lib/data/    core data models: attribute schema, spans, factual statements, constraints
config/
  prompt_templates/             prompts for each stage
  dataset_variable_constraints/ YAML variable constraints (templates + Slovak variable set)
data/          annotation manuals, attribute schemas and evaluation samples — see data/README.md
docs/          per-stage notes
```

## Scope

This repository contains the extraction pipeline, the prompts and the schemas/manuals used
in the paper. It does **not** contain the annotation interface used for the human reference
annotations (INCEpTION), the desktop annotation application built on top of this pipeline,
or scripts that recompute the agreement and accuracy numbers in Tables 1–3 — those were
produced from the curated reference annotations and are reported in the paper.

The full corpus of Slovak judgments is not redistributed here; see `data/README.md`.

## Citation

```bibtex
@inproceedings{knap2026unlocking,
  title     = {Unlocking Criminal Court Decisions: Flexible Information Extraction for Empirical Legal Research},
  author    = {Knap, Tom{\'a}{\v s} and Kvapil{\'i}kov{\'a}, Ivana and {\v C}ern{\'y}, Jan and Bendov{\'a}, Kl{\'a}ra and {\v S}avelka, Jarom{\'i}r and Pour, Vojt{\v e}ch and Dr{\'a}pal, Jakub},
  booktitle = {Legal Knowledge and Information Systems: JURIX 2026},
  series    = {Frontiers in Artificial Intelligence and Applications},
  publisher = {IOS Press},
  year      = {2026}
}
```

## Authors

| | |
|---|---|
| Tomáš Knap (corresponding) | Faculty of Law, Charles University · [0009-0009-2085-9182](https://orcid.org/0009-0009-2085-9182) |
| Ivana Kvapilíková | Faculty of Mathematics and Physics, Charles University · [0000-0003-1479-3294](https://orcid.org/0000-0003-1479-3294) |
| Jan Černý | Faculty of Law, Charles University · [0009-0006-4873-8233](https://orcid.org/0009-0006-4873-8233) |
| Klára Bendová | Faculty of Mathematics and Physics, Charles University · [0000-0001-8002-6566](https://orcid.org/0000-0001-8002-6566) |
| Jaromír Šavelka | School of Computer Science, Carnegie Mellon University · [0000-0002-3674-5456](https://orcid.org/0000-0002-3674-5456) |
| Vojtěch Pour | Faculty of Law, Charles University · [0009-0005-4075-6579](https://orcid.org/0009-0005-4075-6579) |
| Jakub Drápal | Faculty of Law, Charles University · [0000-0001-9455-9013](https://orcid.org/0000-0001-9455-9013) |

## License

Code is released under the MIT License (`LICENSE`). Data files under `data/` are released
under CC BY 4.0 — see `data/README.md`.
