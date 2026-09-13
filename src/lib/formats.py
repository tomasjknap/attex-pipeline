import json
import re


def get_json_from_noisy_json(raw_string: str) -> dict:
    """
    TODO: napsat přesný účel
    """
    stripped = ""
    braces = 0
    for s in raw_string:
        if s == "{":
            braces += 1
        if braces >= 1:
            stripped += s
        if s == "}":
            braces -= 1
    return json.loads(stripped, strict=False)


def break_line_cleaner(text: str) -> str:
    """
    Join soft-wrapped lines while keeping paragraph breaks intact.

    Parameters
    ----------
    text : str
        Text whose single newlines are wrapping artefacts rather than
        structure, such as prose reflowed to fit a column limit.

    Returns
    -------
    str
        The text with single newlines replaced by a space, runs of three or
        more newlines capped at two, and surrounding whitespace removed.

    Notes
    -----
    Single newlines become spaces, so the input must not rely on them to
    carry meaning. Numbered lists, one-rule-per-line blocks, and any other
    line-structured text are flattened into a single paragraph; separate
    those parts with a blank line if they must survive.

    Line endings are normalised first, so CRLF and CR input behave the same
    as LF. Horizontal whitespace around each break is dropped, which means a
    line of only spaces still reads as a paragraph break and rejoined lines
    never gain a double space.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Drop horizontal whitespace hugging a break so rejoined lines get exactly
    # one space and a blank-looking line still counts as a paragraph break.
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)

    # Replace 3 or more consecutive newlines with exactly 2
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Remove single newlines (newlines not preceded or followed by another newline)
    text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)

    return text.strip()
