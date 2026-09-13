from dataclasses import dataclass
from typing import List

from lib.data.attribute_schema import Attribute

"""
ANNOTATED TEXT FORMAT:

Lorem ipsum dolor sit amet, <attr_1>consectetuer adipiscing</attr_1> elit. Sed convallis magna eu sem.
Pellentesque habitant morbi tristique senectus et netus et malesuada fames ac turpis
egestas. Maecenas lorem. Nulla non arcu lacinia neque faucibus fringilla.
"""


@dataclass
class Span:
    """
    Represents a span of text with a specific attribute. It is defined as a continuous
    substring with a start and end index in the full text.
    """

    attribute: Attribute
    start: int
    end: int


class SpannedText:
    """
    Represents a text with annotated spans. Each span is associated with an attribute.
    Multiple spans can share the same attribute. Spans can be nested but they can not overlap.

    Syntax of anotated text is XML-like tags.
    """

    def __init__(self, annotated_text: str):
        """
        parse LLM output and initialize the SpannedText object.
        """
        raise NotImplementedError

    def get_spans(self) -> List[Span]:
        """Returns a list of all spans in the text."""
        raise NotImplementedError

    def get_text(self) -> str:
        """Returns the full text."""
        raise NotImplementedError

    def get_spans_content(self, attribute_name: str) -> List[str]:
        """Returns the content of all spans with the given ID."""
        raise NotImplementedError

    def to_json(self):
        """Serializes the spanned text to a JSON-compatible dictionary."""
        raise NotImplementedError
