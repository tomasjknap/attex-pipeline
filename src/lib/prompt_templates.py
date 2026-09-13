from pathlib import Path
import re
from typing import Any


PLACEHOLDER_PATTERN = re.compile(r"(?<!\{)\{([A-Za-z_][A-Za-z0-9_]*)\}(?!\})")


def get_project_root() -> Path:
    """
    Return the repository root directory.

    Returns
    -------
    Path
        Absolute path to the repository root.
    """
    current_path = Path(__file__).resolve()

    for parent in current_path.parents:
        if (parent / "pyproject.toml").exists():
            return parent

    raise FileNotFoundError("Could not find project root with pyproject.toml.")


def get_prompt_template_path(prompt_name: str) -> Path:
    """
    Build the path to a prompt template stored in the config directory.

    Parameters
    ----------
    prompt_name : str
        Prompt template name, with or without the ``.md`` suffix.

    Returns
    -------
    Path
        Absolute path to the prompt template file.
    """
    normalized_prompt_name = prompt_name

    if not normalized_prompt_name.endswith(".md"):
        normalized_prompt_name = f"{normalized_prompt_name}.md"

    return get_project_root() / "config" / "prompt_templates" / normalized_prompt_name


def load_prompt_template(template_path: str) -> str:
    """
    Load a prompt template from a UTF-8 text file.

    Parameters
    ----------
    template_path : str
        Path to the prompt template file.

    Returns
    -------
    str
        Raw prompt template text.
    """
    return Path(template_path).read_text(encoding="utf-8")


def load_prompt_template_by_name(prompt_name: str) -> str:
    """
    Load a prompt template from the config directory by prompt name.

    Parameters
    ----------
    prompt_name : str
        Prompt template name, with or without the ``.md`` suffix.

    Returns
    -------
    str
        Raw prompt template text.
    """
    template_path = get_prompt_template_path(prompt_name)
    return load_prompt_template(str(template_path))


def get_prompt_template_variables(template_text: str) -> set[str]:
    """
    Collect named placeholders used in a prompt template.

    Parameters
    ----------
    template_text : str
        Prompt template text using ``{placeholder_name}`` placeholders.

    Returns
    -------
    set[str]
        Placeholder names referenced in the template.
    """
    return set(PLACEHOLDER_PATTERN.findall(template_text))


def render_prompt_template(
    template_text: str,
    variables: dict[str, Any],
) -> str:
    """
    Fill named placeholders in a prompt template.

    Parameters
    ----------
    template_text : str
        Prompt template text using ``{placeholder_name}`` placeholders.
    variables : dict[str, Any]
        Mapping from placeholder names to substitution values.

    Returns
    -------
    str
        Rendered prompt text.

    Raises
    ------
    ValueError
        If the provided variables do not match the placeholders used
        in the template.
    """
    expected_variables = get_prompt_template_variables(template_text)
    provided_variables = set(variables)

    missing_variables = sorted(expected_variables - provided_variables)
    unexpected_variables = sorted(provided_variables - expected_variables)

    if missing_variables or unexpected_variables:
        message_parts: list[str] = []

        if missing_variables:
            message_parts.append(f"missing variables: {', '.join(missing_variables)}")

        if unexpected_variables:
            message_parts.append(
                f"unexpected variables: {', '.join(unexpected_variables)}"
            )

        details = "; ".join(message_parts)
        raise ValueError(f"Prompt template variable mismatch: {details}.")

    rendered_template = PLACEHOLDER_PATTERN.sub(
        lambda match: str(variables[match.group(1)]),
        template_text,
    )
    return rendered_template.replace("{{", "{").replace("}}", "}")


def format_attribute_schema(
    attribute_schema: dict[str, dict[str, Any]],
) -> str:
    """
    Convert attribute definitions into prompt text.

    Parameters
    ----------
    attribute_schema : dict[str, dict[str, Any]]
        Mapping from attribute name to a nested attribute specification
        that contains at least a ``description`` field.

    Returns
    -------
    str
        Attribute definitions formatted for prompt insertion.
    """
    if not attribute_schema:
        return ""

    sections: list[str] = []

    for attribute_name, details in attribute_schema.items():
        if not isinstance(details, dict):
            raise ValueError(
                "Attribute schema must contain nested objects with at least "
                f'a "description" field. Invalid value for "{attribute_name}".'
            )
        if "description" not in details:
            raise ValueError(
                "Attribute schema must contain nested objects with at least "
                f'a "description" field. Missing "description" for '
                f'"{attribute_name}".'
            )

        sections.append(f"### {attribute_name}")
        sections.append(f"Description: {details['description']}")

        if "cardinality" in details:
            sections.append(f"Cardinality: {details['cardinality']}")

        if "categories" in details and isinstance(details["categories"], dict):
            sections.append("Categories:")
            for label, description in details["categories"].items():
                sections.append(f"- {label}: {description}")

        if "format" in details:
            sections.append(f"Format: {details['format']}")

        if "instructions" in details:
            sections.append(f"Instructions: {details['instructions']}")

        if "examples" in details and isinstance(details["examples"], dict):
            examples = details["examples"]

            if "correct" in examples:
                sections.append("Correct examples:")
                for example in examples["correct"]:
                    sections.append(f"- {example}")

            if "incorrect" in examples:
                sections.append("Incorrect examples:")
                for example in examples["incorrect"]:
                    sections.append(f"- {example}")

        sections.append("")

    return "\n".join(sections)
