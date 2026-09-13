# Attribute exploration — `a_attribute_explorer.py`

Induces an attribute schema from a corpus of factual statements. Statements are processed in
fixed-size batches against the current schema; residual information not covered by existing
attributes is passed to an LLM, which proposes candidate attributes for subsequent batches.

## Inputs

- input CSV with `judgement_slt_id` and `judgement_factual_sentence` columns
  (optionally `judgement_model_short` for `--category` filtering)
- initial attribute schema JSON — may be a minimal seed (`data/initial_attributes.json`)
  or an expert-provided schema

## Example command

From the repository root:

```bash
uv run src/a_attribute_explorer.py \
  -i data/dui_dev_sample.csv \
  -o dui_schema_induced.json \
  -a data/initial_attributes.json \
  -c B \
  -p openai -m gpt-5.6-terra -t 1.0 --reasoning none \
  -b 10 \
  --schema-update-batch-size 100 \
  --population-threshold 0.85 \
  -s 40
```

## Arguments

- `-i`, `--input`: input CSV with factual statements
- `-o`, `--output`: output attribute schema JSON
- `-a`, `--initial-attributes`: initial (seed or expert) attribute schema JSON
- `-c`, `--category`: filter rows by the value of `judgement_model_short`
- `-p`, `--provider`: LLM provider (`openai`, `genai`, `groq`, `ufalai`)
- `-m`, `--model`: model name
- `-t`, `--temperature`: temperature
- `--reasoning`: reasoning effort level
- `-b`, `--parallel-batch-size`: statements processed in parallel at once
- `--schema-update-batch-size`: induction batch size *N* — how many statements' residuals are
  pooled before proposing new attributes
- `--population-threshold`: minimum share of statements in which an attribute must be
  populated to be retained
- `-s`, `--sample`: limit to the first N statements

## Choosing the induction batch size

`--schema-update-batch-size` is the main control over semantic granularity. Small batches
see little evidence per induction call and tend to propose overly specific, often
case-specific attributes; large batches raise context demands and may overlook rare but
genuine ones. On the 200-statement DUI sample, batch size 100 produced 39 attributes (33% of
them populated in under 5% of statements) against 30 attributes (13% under 5%) for batch
size 200.

Low population alone is not a sufficient pruning criterion — rare attributes such as
`activeDrivingBan` (3.5%) or `attemptedBribeOrCorruption` (0.5%) may still matter for the
research question. Treat the induced schema as a set of candidates for expert review.
