# Data

Small artefacts needed to run and inspect the pipeline. The two offence categories studied
in the paper are abbreviated here:

- **DUI** — driving under the influence (Slovak: *jazda pod vplyvom*)
- **DDB** — driving despite an imposed driving ban (Slovak: *marenie výkonu úradného rozhodnutia*)

## Files

| File | Rows | What it is |
|------|------|------------|
| `initial_attributes.json` |Minimal seed schema (one attribute) handed to attribute exploration when no expert schema is given. |
| `dui_attribute_schema.json` | — | Attribute schema for DUI: per attribute a description, cardinality and value format. |
| `ddb_attribute_schema.json` | — | Attribute schema for DDB, same structure. |
| `ddb_annotation_manual.json` | — | Annotation manual for DDB — the shared specification used both by human annotators and by the extraction prompts. |
| `dui_dev_sample.csv` | 136 | Development sample of DUI factual sentences, with the conduct-based category column (`judgement_model_short`) used by `--category`. |
| `dui_test_set.csv` | 200 | The 200 sampled DUI factual sentences used in the experiments. |
| `ddb_test_set.csv` | 200 | The 200 sampled DDB factual sentences used in the experiments. |
| `ddb_spans_and_values.csv` | 369 | Extracted spans and values for DDB, one column pair (`<attribute>.span`, `<attribute>.value`) per attribute; repeated attributes are indexed (`additionalTrafficViolations.0.span`). Input for value normalization. |

CSV schema for the statement files: `judgement_slt_id` (judgment identifier),
`judgement_factual_sentence` (the factual-behaviour passage), and for the dev sample
`judgement_model_short` (conduct-based category).

## Provenance

Factual sentences are passages from Slovak criminal court judgments issued 2018–2022,
published by the Slovak Ministry of Justice and collected and linked to administrative
records in earlier work. Personal identifiers are pseudonymised in the published source
judgments (e.g. `Q.-XXXEU` for a licence plate).

## Not included here

The full judgment corpus (126,795 judgments) and the complete tagged span export used by the
annotation application are not redistributed in this repository. <!-- TODO: replace with the
Zenodo record and DOI once deposited. -->

## License

Data files in this directory are released under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The underlying court judgments are
public documents of the Slovak Republic.
