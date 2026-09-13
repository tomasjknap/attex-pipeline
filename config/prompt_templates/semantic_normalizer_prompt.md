You assign one normalization strategy to an extracted attribute based on the
observed values.

ATTRIBUTE NAME
{attribute_name}

VALUE STATISTICS
- total observed values: {total_value_count}
- unique observed values: {unique_value_count}
- derived cardinality: {cardinality}

SAMPLED VALUES WITH FREQUENCIES
{sampled_values}

Choose exactly one normalization class:

1. "standardizable_by_category"
Use this when the values should be clustered into a small, stable set of
semantic categories.

2. "standardizable_by_format"
Use this when the values are diverse on the surface, but they follow a
normalizable format such as dates, times, durations, numeric expressions,
identifiers, or other rule-based formats.

3. "split_into_multiple_attributes"
Use this when the attribute should be decomposed into two or more separate
attributes, for example value and unit, place and street, make and model, or
another repeated composite structure.

4. "not_standardizable"
Use this when the values are too diverse, too open-ended, or too context-bound
to normalize in a useful and stable way.

Return only JSON in this shape:
For "standardizable_by_category":
{{"normalization_class": "standardizable_by_category", "categories": {{"LABEL": "description"}}}}

For "standardizable_by_format":
{{"normalization_class": "standardizable_by_format", "formatting_rule": "rule"}}

For "split_into_multiple_attributes" or "not_standardizable":
{{"normalization_class": "split_into_multiple_attributes"}}
{{"normalization_class": "not_standardizable"}}

The value of "normalization_class" must be exactly one of:
- "standardizable_by_category"
- "standardizable_by_format"
- "split_into_multiple_attributes"
- "not_standardizable"

Rules for additional fields:
- If you choose "standardizable_by_category", include "categories" as an object
  mapping category labels to short descriptions.
- Category labels must be in English, written in capital letters, and should
  be short, stable identifiers suitable for schema keys, for example "CAR",
  "MOTORCYCLE", "URBAN", "OTHER".
- If you choose "standardizable_by_format", include "formatting_rule" as a
  short normalization rule string such as "DD.MM.YYYY" or "[float] [unit]".
- Do not include "categories" for other classes.
- Do not include "formatting_rule" for other classes.
