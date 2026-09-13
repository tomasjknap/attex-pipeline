# Span extraction — `d_dataset_builder.py`

## Usage

The dataset builder reads factual statements from a CSV file, sends them to
an LLM in parallel batches, parses the extracted JSON, and writes a flat CSV
table.

### Inputs

- input CSV file with factual statements
- attribute schema JSON

## Example command

From the repository root:

```bash
uv run src/d_dataset_builder.py \
  -i data/dui_dev_sample.csv \
  -o dui_extracted.csv \
  -a data/dui_attribute_schema.json \
  --method extract_spans_and_values \
  -p openai \
  -m gpt-5.6-terra \
  -t 1.0 \
  --reasoning none \
  -b 10
```

## Sample run on a smaller subset

```bash
uv run src/d_dataset_builder.py \
  -i data/dui_dev_sample.csv \
  -o dui_extracted_sample.csv \
  -a data/dui_attribute_schema.json \
  --method extract_spans_and_values \
  -p openai \
  -m gpt-5.6-terra \
  -t 1.0 \
  --reasoning none \
  -b 5 \
  -s 20
```

## Arguments

- `-i`, `--input`: input CSV file
- `-o`, `--output`: output CSV file
- `-a`, `--attribute-schema`: nested attribute schema JSON
- `--method`: dataset building method, including
  `extract_spans_and_values` and `extract_spans_and_values_per_attribute`
- `-p`, `--provider`: LLM provider
- `-m`, `--model`: model name
- `-t`, `--temperature`: temperature
- `--reasoning`: reasoning effort
- `-b`, `--batch-size`: number of statements processed in parallel
- `-s`, `--sample`: limit the number of processed rows
- `--checkpoint-path`: checkpoint base path prefix

## Output format

The output is a flat CSV table.

Single-valued attributes are written as columns such as:

- `dateOfOffense.span`
- `dateOfOffense.value`
- `vehicleType.class`

Multi-valued attributes are written with indexed columns such as:

- `amountUsed.0.span`
- `amountUsed.0.value`
- `amountUsed.1.span`
- `amountUsed.1.value`

Missing values are written as `n/a`.

## Checkpointing and Resume

The builder stores intermediate results in a reusable checkpoint store:

- `<checkpoint>.state.json`: processed item IDs and metadata
- `<checkpoint>.records.jsonl`: append-only processed row records

If `--checkpoint-path` is omitted, the default checkpoint base path is:

- `<output>.checkpoint`

Behavior:

- Each successfully processed row is appended to the checkpoint records file.
- The final CSV is rebuilt from checkpoint records after processing finishes.
- Re-running the same command skips rows already listed in the checkpoint.
- If the process is interrupted, checkpoint records remain available for the
  next run.
- Failed rows are not checkpointed and are retried on the next run.
- Library callers may request a cooperative stop. The builder finishes and
  checkpoints the active batch, then a later call with the same checkpoint
  skips completed IDs and resumes the remaining rows.

The schema decides whether an attribute should also produce:

- `.class` columns when the attribute defines `categories`
- `.value` columns when the attribute defines `format`

## Method Requirements

- `extract_spans_and_values`: requires `--attribute-schema`
- `extract_spans_and_values_per_attribute`: requires `--attribute-schema`
  and extracts each attribute in a separate LLM call for every row
- `tag_spans`: requires `--attribute-schema`
- `copy_spans_and_extract_values`: requires `--attribute-schema` and a
  `tagged_sentence` column in the input CSV
- `langextract`: recognized but not implemented yet
