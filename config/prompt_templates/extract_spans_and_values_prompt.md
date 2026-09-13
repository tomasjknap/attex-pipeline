Extract the following attributes into a JSON structure.
    Go through the given sentence and return JSON with the following structure:
    {{"attribute_name1":{{"span": "...", "value": "...", "class": "..."}}, ...}}
    Span is a verbatim excerpt of the text, value is standardized based in a given format and class is a label. Usually either a class or a value is returned per attribute.

    ATTRIBUTE DEFINITIONS

    {attribute_schema}
    
    Do not include redundant words (‘the day of’, ‘around’, ‘at the time’, etc.) unless they are part of the meaning.
    If a value is anonymized (e.g., XX.XX.XXXX, ANONYMIZED), still extract it. Anonymized data are extracted including the period.
    If attribute is of type "single", extract information into a single value. If the attribute is single but the relevant information is spread across the text, the span will only include the first part of the information but class/value must reflect the full context.
    If attribute is of type "multiple", extract separate pieces of information separately in a list with preserved order (e.g. 0.5 mg/l of alcohol and 0.001 ng/l of THC ==> [0.5 mg/l ,  0.001 ng/l], [alcohol, THC])
    If an identical piece of information is repeated, do not extract it again.
    
    When relevant, add attribute class and/or value to the JSON according to the
    attribute definition.
    When a list of categories is defined for an attribute, pick the correct
    category and add it to the "class" key.
    When a format is defined for an attribute, apply it and add it to the
    "value" key.
    If the tag content is anonymized and no class rule is defined, then value="ANONYMIZED"
    If the attribute is not present in the text, then value="NOT_PRESENT"
    If it is not possible to standardize using the categories or the format, then value="NON_STANDARDIZABLE" (use also when there are multiple pieces of information for a single-type attribute and you have no instructions which one to consider).
    If no category list or format is provided, do not add either class nor value.
    
    INPUT:
    dňa 25. januara 2018 v čase okolo 02.50 h v Stupave na Železničnej ulicu, ako vodič viedol osobné motorové vozidlo mačky O. T., pričom u vodiča bola vykonaná dychová skúška prístrojom AlcoQuant 6020 plus, ktorou bola zistená hodnota 0,87 mg/l o 02.55 h a následne opakovaným meraním hodnota 0,82 mg/l o 03.10 h.
    OUTPUT:
    {
          "dateOfOffense": {
            "span": "25. januara 2018",
            "value": "25.01.2026",
          },
          "timeOfOffense": {
            "span": "02.50 h",
            "value": "02:50",
          },
          "vehicleType": {
            "span": "osobné motorové vozidlo",
            "class": "CAR"
          },
          "vehicleModel": {
            "span": "O. T.",
            "value": "O. T.",
          },
          "measuringMethod": {
            "span": "dychová skúška",
            "class": "BREATH"
          },
          "measuringDevice": {
            "span": "AlcoQuant 6020 plus",
            "value": "AlcoQuant 6020 plus",
          },
          "amountUsed": [
            {
              "span": "0,87 mg/l",
              "value": "0.87 mg/l",
            },
            {
              "span": "0,82 mg/l",
              "value": "0.82 mg/l",
            }
          ],
          "measuringTime": [
            {
              "span": "02.55",
              "value": "02:55",

            },
            {
              "span": "03.10",
              "value": "03:10",
            }
          ]
    }
