from lib.data.attribute_schema import AttributeSchema
from lib.data.text_spans import SpannedText


class FactualStatement:
    """
    A class representing a factual statemnet with spanned text and extracted attributes.
    """

    judgement_slt_id: str
    judgement_factual_statement: str
    spanned_judgement_factual_statement: SpannedText
    attributes: AttributeSchema

    def to_json(self):
        """
        TODO: Implement conversion to JSON format
        """
        raise NotImplementedError("to_json method is not implemented yet.")

    def to_pd_dataframe(self):
        """
        TODO: Implement conversion to pandas DataFrame
        """
        raise NotImplementedError("to_pd_dataframe method is not implemented yet.")


class FactualStatementCollection:
    """
    A collection of factual statements associated with judgement SLT IDs.

    TODO: Make this class iterable over its factual statements.
    """

    def load_csv(self):
        """
        TODO: Implement loading attributes from a CSV file

        format:
            - judgement_slt_id: str
            - judgement_factual_statement: str

        """
        raise NotImplementedError("load_csv method is not implemented yet.")

    def to_pd_dataframe(self):
        """
        TODO: implement conversion to pandas DataFrame
        """
        raise NotImplementedError("to_pd_dataframe method is not implemented yet.")
