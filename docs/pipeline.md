# Pipeline

AttEx extracts structured attributes from *factual statements* — the passages of a criminal
judgment describing the conduct for which the defendant was found guilty.

```
                 annotation manual = extraction schema
                 (id · description · cardinality · value format · category labels)
                        │ configures                      ▲ informs
                        ▼                                 │
factual  ──▶ 1 attribute ──▶ 2 span      ──▶ 3 value  ──▶ structured
statements    exploration     extraction      normalization   dataset
                  ▲                                 │
                  └────── induction loop            └────── researcher revision cycle
```

## 1 — Attribute exploration (`src/a_attribute_explorer.py`)

Statements are processed in fixed-size batches against the current schema. Each round makes
two extraction calls per statement — one for known attributes and one for residual
information — plus one induction call per batch, which proposes candidate attributes from
the residuals. Accepted candidates are merged into the schema.

Granularity is controlled by three levers:

- `--schema-update-batch-size` — induction batch size *N*. Small batches produce overly
  specific attributes; large batches raise context demands and may overlook rare ones.
- `--population-threshold` — how widely an attribute must be populated to be retained.
- prompt-level constraints in `config/prompt_templates/attribute_extraction_prompt.md`:
  a *non-overlap* constraint rejects proposals subsuming existing attributes, and a
  *recurrence* constraint favours concepts likely to recur across statements.

Frequency alone is not a sufficient filter: rare attributes can still be relevant to the
research question, so the induced schema is treated as a set of candidates for expert review.

## 2 — Span extraction (`src/d_dataset_builder.py`)

Evidence is first extracted as copied text, aligned with the original statement, and then
wrapped in generic XML-like tags with unique identifiers:

```
The defendant drove a <span id="s1">Škoda Octavia</span> on <span id="s2">15 March 2024</span>
with a blood alcohol concentration of <span id="s3">1.24 ‰</span>.
```

Later stages reference these identifiers instead of reproducing or relocating the evidence.
This keeps extracted values traceable to their source and preserves the original expression
before normalization.

Output columns are `<attribute>.span` and `<attribute>.value`; attributes with cardinality
`multiple` are indexed (`additionalTrafficViolations.0.span`).

## 3 — Value normalization (`src/c_semantic_normalizer.py`)

Observed values per attribute are sampled and classified into one of four strategies:

| Class | Meaning |
|-------|---------|
| `standardizable_by_category` | map to a finite set of category labels (e.g. `CAR`, `MOTORCYCLE`) |
| `standardizable_by_format` | convert to a canonical format (dates, times, durations, units) |
| `split_into_multiple_attributes` | the span mixes several concepts and should be separated |
| `not_standardizable` | keep the value as free text |

The strategy is to preserve as much information as possible while minimising semantic
interpretation: transformations that cannot be verified against the supporting evidence are
avoided. The resulting rules become part of the schema and are applied during final
extraction.

## Format validation (`src/e_format_validator.py`)

A built dataset is checked column by column against YAML variable constraints in
`config/dataset_variable_constraints/`. `templates/` holds reusable constraint types
(`date`, `time`, `integer`, `float`, `bool`, `string`, `subset`, `unit`); `vars/SK/` holds the
Slovak variable set. Violations are written as one JSON record per line with `--report`.

## Human oversight

The revision cycle lets researchers align extraction with their analytical objectives by
changing the annotation manual: removing or merging attributes, adjusting categories, and
refining extraction rules after inspecting extracted values and their supporting spans.
Once accepted, the revised manual regenerates annotations consistently across the dataset.

## Data models

`src/lib/data/` holds the core types: `AttributeSchema`/`Attribute` (extracted attribute
definitions), `Span`/`SpannedText` (XML-like annotations; spans may nest but not overlap),
`FactualStatement`/`FactualStatementCollection` (input documents) and `VariableConstraint`
(validation rules).
