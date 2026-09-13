#!/usr/bin/env python3
import datetime
import re
from dataclasses import dataclass
from math import isnan
from typing import Any, ClassVar, Literal

import pandas as pd
import yaml

Severity = Literal["error", "warning"]


@dataclass(frozen=True, slots=True)
class Violation:
    """
    A single constraint-check finding produced by ``VariableConstraint``.

    Attributes
    ----------
    severity : {"error", "warning"}
        ``"error"`` halts ``validate()`` and yields a False result.
        ``"warning"`` is informational and does not affect validity.
    type : str
        The constraint type (e.g. ``"Float"``, ``"Subset"``).
    name : str
        The variable name from the constraint config.
    message : str
        Human-readable description of the finding.
    value : Any
        The value(s) under test at the time the finding was recorded.
    constraints : dict
        Snapshot of the constraints that produced the finding.
    description : str
        The variable description from the constraint config.
    """

    severity: Severity
    type: str
    name: str
    message: str
    value: Any
    constraints: dict[str, Any]
    description: str


class VariableConstraint:
    """
    Base class for a dataset variable validated against its YAML constraints.

    Subclasses parse the raw values into their own type and implement
    ``validate``, recording any failures as ``Violation`` entries.
    """

    _values: list[Any]
    _name: str
    _description: str
    _min_amount: int
    _max_amount: int
    _constraints: dict[str, Any]
    _config: dict[str, Any]
    _type: str
    _edge_cases: list[str]
    _violations: list[Violation]
    _expected_keys: ClassVar[set[str]] = {
        "name",
        "description",
        "type",
        "constraints",
        "min_amount",
        "max_amount",
    }

    def _load_config_file(self, config_file: str) -> dict[str, Any]:
        with open(config_file, "r") as file:
            self._config = yaml.safe_load(file)
        return self._config

    def _violate(self, message: str) -> None:
        """Record an error-level finding against this variable."""
        self._violations.append(
            Violation(
                severity="error",
                type=self._type,
                name=self._name,
                message=message,
                value=self._values,
                constraints=self._constraints,
                description=self._description,
            )
        )

    def _warn(self, message: str) -> None:
        """Record a warning-level finding against this variable."""
        self._violations.append(
            Violation(
                severity="warning",
                type=self._type,
                name=self._name,
                message=message,
                value=self._values,
                constraints=self._constraints,
                description=self._description,
            )
        )

    def is_edge_case(self) -> bool:
        for v in self.values:
            if str(v) in self._edge_cases:
                return True
        return False

    @property
    def values(self) -> Any:
        return self._values

    @property
    def config(self) -> dict[str, Any]:
        return self._config

    @property
    def violations(self) -> list[Violation]:
        """All findings recorded against this variable, in order."""
        return self._violations

    def validate(self) -> bool:
        raise NotImplementedError("Subclasses must implement validate method")

    def __init__(self, raw_values: Any, config: str | dict[str, Any]) -> None:
        self._violations = []

        if isinstance(config, str):
            self._load_config_file(config)
        else:
            self._config = config

        if self._config is None:
            raise ValueError("Config is None")

        for ek in self._expected_keys:
            if ek not in self._config:
                raise ValueError(f"Config file is missing required key: {ek}")

        self._name = self._config.get("name", "NO NAME")
        if self._name == "NO NAME":
            self._warn("Variable has no name")

        self._description = self._config.get("description", "NO DESCRIPTION")
        if self._description == "NO DESCRIPTION":
            self._warn("Variable has no description")

        self._constraints = self._config.get("constraints", {})
        if self._constraints is None:
            self._constraints = {}

        sep = self.config["separator"] if "separator" in self.config.keys() else ";"
        if isinstance(raw_values, str):
            self._values = [v.strip() for v in raw_values.split(sep)]
        else:
            self._values = [str(raw_values)]

        self._min_amount = (
            int(self.config["min_amount"]) if "min_amount" in self._config.keys() else 1
        )
        self._max_amount = (
            int(self.config["max_amount"]) if "max_amount" in self._config.keys() else 1
        )

        if len(self.values) < self._min_amount:
            self._violate(f"Number of values is less than minimum {self._min_amount}")
        if len(self.values) > self._max_amount:
            self._violate(
                f"Number of values is greater than maximum {self._max_amount}"
            )

        self._edge_cases = self.config.get("edge_cases", [])
        if not isinstance(self._edge_cases, list):
            self._warn("Edge cases is not a list, ignoring")
            self._edge_cases = []


class VariableFloat(VariableConstraint):
    """
    Variable whose values are floating-point numbers, optionally range-bounded.
    """

    _values: list[float | str]
    _type: str = "Float"

    def __init__(self, raw_values: str, config: str | dict[str, Any]) -> None:
        super().__init__(raw_values, config)

        parsed_values = []
        for v in self.values:
            try:
                parsed_values.append(float(v))
            except ValueError:
                parsed_values.append(v)
        self._values = parsed_values

        if "max" in self._constraints:
            self._constraints["max"] = float(self._constraints["max"])
        if "min" in self._constraints:
            self._constraints["min"] = float(self._constraints["min"])

    def validate(self) -> bool:
        for v in self.values:
            if str(v) in self._edge_cases:
                continue

            if isnan(v):
                self._violate("Value is NaN")
                return False

            for c in self._constraints.keys():
                match c:
                    case "min":
                        if v < self._constraints[c]:
                            self._violate(
                                f"Value {v} is less than minimum {self._constraints[c]}"
                            )
                            return False
                    case "max":
                        if v > self._constraints[c]:
                            self._violate(
                                f"Value {v} is greater than maximum {self._constraints[c]}"
                            )
                            return False
                    case _:
                        self._warn(f"Unknown constrain {c}")
        return True


class VariableUnit(VariableConstraint):
    """
    Variable holding a numeric magnitude paired with an allowed unit symbol.
    """

    _values: list[tuple[float, str]] | list[tuple]
    _type: str = "unit"

    def __init__(self, raw_values: str, config: str | dict[str, Any]) -> None:
        super().__init__(raw_values, config)

        values: list[tuple] = [tuple(str(v).strip().split()) for v in self.values]
        self._values = values

    def validate(self) -> bool:
        for v in self.values:
            if v[0] in self._edge_cases:
                continue

            if not isinstance(v, tuple):
                self._violate(f"Value {v} is not a tuple")
                return False
            if len(v) != 2:
                self._violate(f"Value {v} does not have 2 elements (value and unit)")
                return False
            try:
                numeric_value = float(v[0])
            except ValueError:
                self._violate(f"Value {v[0]} is not a float")
                return False
            unit = v[1]

            for c in self._constraints.keys():
                match c:
                    case "units":
                        for u in self._constraints["units"]:
                            if unit == u["unit"]:
                                if "min" in u:
                                    if numeric_value < u["min"]:
                                        self._violate(
                                            f"Value {numeric_value} is less than minimum {u['min']} for unit {unit}"
                                        )
                                        return False
                                if "max" in u:
                                    if numeric_value > u["max"]:
                                        self._violate(
                                            f"Value {numeric_value} is greater than maximum {u['max']} for unit {unit}"
                                        )
                                        return False
                                break
                        else:
                            self._violate(f"Unit {unit} is not in allowed units")
                            return False
                    case _:
                        self._warn(f"Unknown constrain {c}")
        return True


class VariableBool(VariableConstraint):
    """
    Variable whose values are booleans written in any accepted textual spelling.
    """

    _values: list[bool]
    _type: str = "Bool"

    def _convert_to_bool(self, value: str) -> bool | None:
        value = value.strip().lower()
        if value in ("1", "true", "t"):
            return True

        elif value in ("0", "false", "f"):
            return False
        return None

    def __init__(self, values: str, config: str | dict[str, Any]) -> None:
        super().__init__(values, config)

        values = []
        for v in values:
            values.append(self._convert_to_bool(v))
        self._values = values
        is_c = self._constraints.get("is", None)
        if not isinstance(is_c, bool) and is_c is not None:
            raise ValueError("'is' constrain must be a boolean value")
        else:
            self._constraints["is"] = is_c

    def validate(self) -> bool:
        for v in self.values:
            if v is None:
                self._violate(f"Value {v} is not a valid boolean value")
                return False
            if "is" in self._constraints.keys():
                if v != self._constraints["is"]:
                    self._violate(f"Value {v} is not {self._constraints['is']}")
                    return False
        return True


class VariableSubset(VariableConstraint):
    """
    Variable whose values must all come from a fixed allowed set.
    """

    _type: str = "Subset"
    _values: list[str]

    def __init__(self, raw_values: Any, config: str | dict[str, Any]) -> None:
        super().__init__(raw_values, config)

    def validate(self) -> bool:
        for v in self.values:
            if "allowed_values" in self._constraints.keys():
                if v not in self._constraints["allowed_values"]:
                    self._violate(
                        f"Value {v} is not in allowed values {self._constraints['allowed_values']}"
                    )
                    return False
        if self._constraints.get("unique", False):
            if len(self._values) != len(set(self._values)):
                self._violate(
                    "List contains duplicate values but 'unique' constrain is set to True"
                )
                return False
        return True


class VariableString(VariableConstraint):
    """
    Free-text variable constrained by length and optional pattern rules.
    """

    _values: str
    _type: str = "string"

    def __init__(self, raw_values: str, config: str | dict[str, Any]) -> None:
        super().__init__(raw_values, config)

        if self._constraints.get("min_length", None) is not None:
            self._constraints["min_length"] = int(self._constraints["min_length"])
        if self._constraints.get("max_length", None) is not None:
            self._constraints["max_length"] = int(self._constraints["max_length"])

    def validate(self) -> bool:
        for v in self.values:
            for c in self._constraints.keys():
                match c:
                    case "min_length":
                        if len(v) < self._constraints["min_length"]:
                            self._violate(
                                f"String length is less than minimum {self._constraints[c]}"
                            )
                            return False
                    case "max_length":
                        if len(v) > self._constraints["max_length"]:
                            self._violate(
                                f"String length is greater than maximum {self._constraints[c]}"
                            )
                            return False
                    case "regex":
                        if not re.match(self._constraints["regex"], v):
                            if v not in self._edge_cases:
                                self._violate(
                                    f"Value does not match regex {self._constraints[c]}"
                                )
                                return False
                    case _:
                        self._warn(f"Unknown constrain {c}")
        return True


class VariableDate(VariableConstraint):
    """
    Variable whose values are calendar dates parsed from a configured format.
    """

    _values: list[datetime.date | str]
    _type: str = "date"

    def __init__(self, raw_values: str, config: str | dict[str, Any]) -> None:
        super().__init__(raw_values, config)

        parsed_values = []
        for v in self.values:
            try:
                parsed_values.append(datetime.datetime.strptime(v, "%Y-%m-%d").date())
            except ValueError:
                parsed_values.append(v)
        self._values = parsed_values

    def validate(self) -> bool:
        for v in self.values:
            if str(v) in self._edge_cases:
                continue

            if not isinstance(v, datetime.date):
                self._violate(f"Value {v} is not a valid date (YYYY-MM-DD)")
                return False

            for c in self._constraints.keys():
                match c:
                    case "earliest":
                        min_date = datetime.datetime.strptime(
                            self._constraints[c], "%Y-%m-%d"
                        ).date()
                        if v < min_date:
                            self._violate(
                                f"Date is earlier than minimum {self._constraints[c]}"
                            )
                            return False
                    case "latest":
                        max_date = datetime.datetime.strptime(
                            self._constraints[c], "%Y-%m-%d"
                        ).date()
                        if v > max_date:
                            self._violate(
                                f"Date is later than maximum {self._constraints[c]}"
                            )
                            return False
                    case _:
                        self._warn(f"Unknown constrain {c}")
        return True


class VariableInteger(VariableConstraint):
    """
    Variable whose values are whole numbers, optionally range-bounded.
    """

    _values: list[int | str]
    _type: str = "Integer"

    def __init__(self, raw_values: str, config: str | dict[str, Any]) -> None:
        super().__init__(raw_values, config)

        parsed_values: list[int | str] = []
        for v in self.values:
            try:
                parsed_values.append(int(v))
            except ValueError:
                parsed_values.append(v)
        self._values = parsed_values

        if "min" in self._constraints:
            self._constraints["min"] = int(self._constraints["min"])
        if "max" in self._constraints:
            self._constraints["max"] = int(self._constraints["max"])

    def validate(self) -> bool:
        for v in self.values:
            if str(v) in self._edge_cases:
                continue

            if not isinstance(v, int):
                self._violate(f"Value {v} is not an integer")
                return False

            for c in self._constraints.keys():
                match c:
                    case "min":
                        if v < self._constraints[c]:
                            self._violate(
                                f"Value {v} is less than minimum {self._constraints[c]}"
                            )
                            return False
                    case "max":
                        if v > self._constraints[c]:
                            self._violate(
                                f"Value {v} is greater than maximum {self._constraints[c]}"
                            )
                            return False
                    case "allowed_values":
                        if v not in self._constraints[c]:
                            self._violate(
                                f"Value {v} is not in allowed values {self._constraints[c]}"
                            )
                            return False
                    case _:
                        self._warn(f"Unknown constrain {c}")
        return True


def variable_factory(variable_name: str, config_path: str) -> VariableConstraint:
    config = yaml.safe_load(open(config_path, "r"))
    match config["type"]:
        case "float":
            return VariableFloat(variable_name, config)
        case "unit":
            return VariableUnit(variable_name, config)
        case "bool":
            return VariableBool(variable_name, config)
        case "subset":
            return VariableSubset(variable_name, config)
        case "string":
            return VariableString(variable_name, config)
        case "date":
            return VariableDate(variable_name, config)
        case "integer":
            return VariableInteger(variable_name, config)
        case _:
            raise Exception(f"Invalid variable type: {config['type']}")


def validate_dataset(df: pd.DataFrame, constraints_dir: str) -> tuple[int, int]:
    count_valid = 0
    count_invalid = 0

    for column in df.columns:
        constraints_path = f"{constraints_dir}/{column}.yml"
        for _, row in df.iterrows():
            raw_value = str(row[column])
            constraint = variable_factory(raw_value, constraints_path)
            if constraint.validate():
                count_valid += 1
            else:
                count_invalid += 1
    return count_valid, count_invalid
