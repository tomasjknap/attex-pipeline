from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class Attribute:
    """
    Represents a single attribute with its metadata.
    """

    name: str  # Name of the attribute
    description: str  # Description of the attribute in natural language
    data_format: Optional[str] = None
    constraints: Optional[List[str]] = None
    value: Optional[Any] = None


@dataclass
class AttributeSchema:
    """
    TODO: Make this class iterable
    TODO: Make this tree structure to allow nested attributes
    """

    attributes: Dict[str, Attribute]
