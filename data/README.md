# Data

Evaluation data for the two offence types studied in the paper:

- **DUI** — driving under the influence of alcohol or other addictive substances (no consequence)
- **DDB** — driving despite a driving ban

Each dataset contains 200 factual sentences sampled from Slovak criminal judgments, the
annotation manual and attribute schema used for them, two independent human annotations,
a curated gold standard reconciled from the two annotations, and LLM extractions produced by
`src/d_dataset_builder.py`.

```
data/
  initial_attributes.json   minimal seed schema for attribute exploration
  dui_dev_sample.csv        DUI development sample for attribute exploration
  DDB/                      driving despite a driving ban
  DUI/                      driving under the influence (two annotation projects)
```

## Shared files

| File | What it is |
|------|------------|
| `initial_attributes.json` | Minimal seed schema (one attribute) handed to attribute exploration when no expert schema is given. |
| `dui_dev_sample.csv` | 40 DUI factual sentences used for developing attribute exploration, with the conduct-based category column (`judgement_model_short`) used by `--category`. Disjoint from the DUI test set. |

## DDB — driving despite a driving ban

| File | What it is |
|------|------------|
| `ddb_test_set.csv` | The 200 sampled DDB factual sentences (pipeline input). |
| `ddb_annotation_manual.pdf` | Annotation manual (in Czech) given to the human annotators. |
| `ddb_attribute_schema.json` | The same manual as an attribute schema (11 attributes: description, cardinality, value format or categories) — used by the extraction prompts. |
| `ddb_annotator_0.csv`, `ddb_annotator_1.csv` | Annotations by two independent annotators. |
| `ddb_annotators_curated_gold.csv` | Curated gold standard reconciled from the two annotations. |
| `ddb_extracted_<model>.csv` | LLM extractions for `gpt-5-mini`, `gpt-5.2` and `gpt-5.6-terra` (two runs: `gpt-5.6-terra`, `gpt-5.6-terra_run2`). |
| `ddb_normalization_schema.json` | Broader exploratory schema (16 attributes) behind `ddb_spans_and_values.csv`. |
| `ddb_spans_and_values.csv` | Spans and values extracted with `ddb_normalization_schema.json` from a separate sample of 200 DDB sentences (not the test set). Input for value normalization (`src/c_semantic_normalizer.py`). |

DDB annotations are value-level: annotators record a normalized value or a category per
attribute, without marking spans. Values follow the formats in the schema; `ANONYMIZED` /
`anonymized` marks anonymized information and `NOT_PRESENT` / `not_present` information that
is not stated in the sentence.

## DUI — driving under the influence

DUI was annotated in two projects over the same 200 sentences, each with its own version of the
manual and schema. All files of one project share the `dui_project1_` or `dui_project2_` prefix.
`project1` corresponds to **Schema 1** in the paper (the initial instructions) and `project2` to
**Schema 2** (revised after the first annotation and extraction results).

| Project | Manual version | Attributes | Notes |
|---------|----------------|------------|-------|
| `project1` | 3.1 | 17 | `timeOfOffense` keeps the preposition "pred" in the span; `refusedTesting` is annotated both when the test was refused (`True`) and when it was taken (`False`) |
| `project2` | 5.1.2 | 18 | adds `geographicalDetails`; `timeOfOffense` excludes prepositions; `refusedTesting` is annotated only for a refusal; closed category sets (e.g. for `reasonForCheck`) |

| File | What it is |
|------|------------|
| `dui_test_set.csv` | The 200 sampled DUI factual sentences (pipeline input), identical in both projects. |
| `dui_projectN_annotation_manual.pdf` | Annotation manual (in Czech) given to the human annotators. |
| `dui_projectN_attribute_schema.json` | The same manual as an attribute schema (description, cardinality, correct/incorrect examples) — used by the extraction prompts. |
| `dui_projectN_annotator_0.csv`, `dui_projectN_annotator_1.csv` | Annotations by two independent annotators. |
| `dui_projectN_annotators_curated_gold.csv` | Curated gold standard reconciled from the two annotations. |
| `dui_project1_extracted_gpt-5.6-terra.csv` | LLM extraction with the project 1 schema. |
| `dui_project2_extracted_<model>.csv` | LLM extractions with the project 2 schema for `gpt-5-mini`, `gpt-5` and `gpt-5.6-terra` (two runs). `gpt-5` covers 198 sentences: no output was returned for `115884510` and `116173965`. |

DUI annotations are span-level. For every attribute the annotation files have three columns:

- `<Attribute>.text` — the annotated span
- `<Attribute>.value` — the normalized value or category (categorical attributes only)
- `<Attribute>.position` — character offsets `(start, end)` into `text`, 0-based, end exclusive

Multiple spans of one attribute are separated by `; ` in all three columns. In the gold files
every column carries the suffix `.curated`.

## Column formats

**Sentence files** (`*_test_set.csv`, `dui_dev_sample.csv`): `judgement_slt_id` (judgment
identifier), `judgement_factual_sentence` (the factual-behaviour passage), and for the dev
sample `judgement_model_short` (conduct-based category).

**Annotation files**: `id` (= `judgement_slt_id`), `text` (= `judgement_factual_sentence`),
then the attribute columns. Attribute names are capitalized (`DateOfOffense`) where the schemas
use camelCase (`dateOfOffense`). DDB annotator files additionally contain `source_file` and
`corruptedSentenceFeatures` (annotators' flag for a damaged sentence; empty for all 200 sentences).

**Extraction files** (`*_extracted_*.csv`, `ddb_spans_and_values.csv`): output of
`src/d_dataset_builder.py` — `judgement_slt_id`, `judgement_factual_sentence`, then one column
pair per attribute: `<attribute>.span` with `<attribute>.value` (or `<attribute>.class` for
categorical attributes). Attributes with multiple cardinality are indexed
(`dateOfOffense.0.span`, `dateOfOffense.1.span`). Missing values are written as `n/a`.

## License

Data files in this directory are released under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The underlying court judgments are
public documents of the Slovak Republic.
