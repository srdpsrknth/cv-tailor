"""Targeted, comment-preserving insertions into a profile's YAML text.

``yaml.safe_dump`` discards comments, quoting and layout, so rewriting a candidate's
hand-maintained profile that way is destructive. These helpers instead locate a node with
PyYAML's composer (which records line and column marks) and insert one line of text, so
every other byte of the file is untouched.

Only shapes this module understands are edited: a missing list key (for example an entry
without ``bullets:``) added after the entry's last key, block sequences of single-line scalars,
single-line flow sequences, an empty ``[]``, and a new key at the end of a block mapping.
Anything else raises :class:`Unsupported`, and the caller decides on a fallback. The
caller is also expected to verify the result by reloading it; nothing here is trusted
blindly.
"""
from __future__ import annotations

import json
import re
from typing import Sequence, Union

import yaml
from yaml.nodes import MappingNode, ScalarNode, SequenceNode

PathPart = Union[str, int]


class Unsupported(Exception):
    """The YAML shape is not one the targeted editor handles safely."""


# --------------------------------------------------------------------------- locating


def _compose(text: str):
    if any(ch in text for ch in ("\x85", " ", " ")) or re.search(r"\r(?!\n)", text):
        raise Unsupported("unusual line separators")
    try:
        return yaml.compose(text.lstrip("﻿"), Loader=yaml.SafeLoader)
    except yaml.YAMLError as error:
        raise Unsupported(f"unparseable YAML: {error}")


def _child(node, part: PathPart):
    """``(key_node_or_None, value_node)`` for one path step."""
    if isinstance(node, MappingNode) and isinstance(part, str):
        for key, value in node.value:
            if isinstance(key, ScalarNode) and key.value == part:
                return key, value
    elif isinstance(node, SequenceNode) and isinstance(part, int):
        if 0 <= part < len(node.value):
            return None, node.value[part]
    raise Unsupported(f"path element {part!r} not found")


def _locate(root, path: Sequence[PathPart]):
    key = None
    node = root
    for part in path:
        key, node = _child(node, part)
    return key, node


# --------------------------------------------------------------------------- rendering


def render_scalar(value: str, style: Union[str, None], *, flow: bool = False) -> str:
    """``value`` as one line of YAML, matching a neighbour's quoting ``style``."""
    if "\n" in value or "\r" in value:
        raise Unsupported("multi-line value")
    if style == '"':
        return json.dumps(value, ensure_ascii=False)
    if style == "'":
        return "'" + value.replace("'", "''") + "'"
    dumped = yaml.safe_dump(
        [value], default_flow_style=False, allow_unicode=True, width=10**9
    ).rstrip("\n")
    if dumped.count("\n") or not dumped.startswith("- "):
        return json.dumps(value, ensure_ascii=False)
    rendered = dumped[2:]
    if flow and re.search(r"[,\[\]{}]", rendered) and not rendered.startswith(('"', "'")):
        return json.dumps(value, ensure_ascii=False)
    return rendered


def _single_line_scalar(node) -> bool:
    return (
        isinstance(node, ScalarNode)
        and node.style in (None, '"', "'")
        and node.start_mark.line == node.end_mark.line
    )


def _last_line(node) -> int:
    """The index of the last line a node occupies, for shapes we can reason about."""
    if isinstance(node, ScalarNode):
        if not _single_line_scalar(node):
            raise Unsupported("multi-line scalar")
        return node.start_mark.line
    if isinstance(node, SequenceNode):
        if node.flow_style:
            if node.start_mark.line != node.end_mark.line:
                raise Unsupported("multi-line flow sequence")
            return node.end_mark.line
        return _last_line(node.value[-1])
    if isinstance(node, MappingNode):
        if node.flow_style:
            raise Unsupported("flow mapping")
        return _last_line(node.value[-1][1])
    raise Unsupported("unknown node")


# --------------------------------------------------------------------------- inserting


def _join(lines: list[str]) -> str:
    return "\n".join(lines)


def _insert_missing_list(text: str, mapping: MappingNode, key: str, value: str) -> str:
    """Add ``key:`` with one item after the last line of a block mapping that lacks it.

    This is the case of an experience entry or project with no ``bullets:`` yet. The new
    key is aligned with the mapping's other keys (also inside a ``- company: X`` list item).
    """
    if mapping.flow_style or not mapping.value:
        raise Unsupported("target is not a non-empty block mapping")
    lines = text.split("\n")
    cr = "\r" if lines and lines[0].endswith("\r") else ""
    first_key = mapping.value[0][0]
    indent = " " * first_key.start_mark.column
    if any(k.start_mark.column != first_key.start_mark.column for k, _ in mapping.value):
        raise Unsupported("inconsistent key indentation")
    last = _last_line(mapping)
    lines[last + 1:last + 1] = [
        f"{indent}{render_scalar(key, None)}:{cr}",
        f"{indent}  - {render_scalar(value, None)}{cr}",
    ]
    return _join(lines)


def insert_list_item(text: str, path: Sequence[PathPart], value: str) -> str:
    """Append ``value`` to the list at ``path``, touching nothing else."""
    root = _compose(text)
    if path and isinstance(path[-1], str):
        _, parent = _locate(root, path[:-1])
        if isinstance(parent, MappingNode) and not any(
            isinstance(k, ScalarNode) and k.value == path[-1] for k, _ in parent.value
        ):
            return _insert_missing_list(text, parent, path[-1], value)
    key, seq = _locate(root, path)
    if not isinstance(seq, SequenceNode):
        raise Unsupported("target is not a list")
    lines = text.split("\n")
    cr = "\r" if lines and lines[0].endswith("\r") else ""

    if not seq.flow_style:
        last = seq.value[-1]
        if not _single_line_scalar(last):
            raise Unsupported("last item is not a single-line scalar")
        index = last.start_mark.line
        match = re.match(r"^(\s*-\s+)", lines[index])
        if not match or len(match.group(1)) != last.start_mark.column:
            raise Unsupported("unexpected list item layout")
        lines.insert(index + 1, match.group(1) + render_scalar(value, last.style) + cr)
        return _join(lines)

    # Flow sequences: one line only.
    if seq.start_mark.line != seq.end_mark.line:
        raise Unsupported("multi-line flow sequence")
    index = seq.start_mark.line
    line = lines[index]
    close = seq.end_mark.column - 1
    if line[close:close + 1] != "]":
        raise Unsupported("could not find the closing bracket")
    if not seq.value:
        if key is None or line[seq.start_mark.column:close + 1].replace(" ", "") != "[]":
            raise Unsupported("unexpected empty list layout")
        before = line[:seq.start_mark.column].rstrip()
        after = line[close + 1:].strip().rstrip("\r")
        lines[index] = before + ("  " + after if after else "") + cr
        item_indent = " " * (key.start_mark.column + 2)
        lines.insert(index + 1, f"{item_indent}- {render_scalar(value, None)}{cr}")
        return _join(lines)
    last = seq.value[-1]
    if not _single_line_scalar(last):
        raise Unsupported("flow list holds non-scalars")
    head = line[:close]
    stripped = head.rstrip()
    gap = head[len(stripped):]
    rendered = render_scalar(value, last.style, flow=True)
    joiner = " " if stripped.endswith(",") else ", "
    lines[index] = stripped + joiner + rendered + gap + line[close:]
    return _join(lines)


def add_mapping_list(text: str, path: Sequence[PathPart], key: str, items: Sequence[str]) -> str:
    """Add ``key: [items]`` as a block list at the end of the block mapping at ``path``."""
    root = _compose(text)
    _, mapping = _locate(root, path)
    if not isinstance(mapping, MappingNode) or mapping.flow_style or not mapping.value:
        raise Unsupported("target is not a non-empty block mapping")
    if any(k.value == key for k, _ in mapping.value if isinstance(k, ScalarNode)):
        raise Unsupported("key already exists")
    lines = text.split("\n")
    cr = "\r" if lines and lines[0].endswith("\r") else ""
    first_key = mapping.value[0][0]
    indent = " " * first_key.start_mark.column
    if first_key.start_mark.line == mapping.start_mark.line and path:
        # ``- key: value`` style entries have a dash before the first key on its line.
        if not re.match(r"^\s*$", lines[first_key.start_mark.line][:first_key.start_mark.column]):
            raise Unsupported("mapping starts inside a list item")
    last = _last_line(mapping)
    new = [f"{indent}{render_scalar(key, None)}:{cr}"]
    new += [f"{indent}  - {render_scalar(item, None)}{cr}" for item in items]
    lines[last + 1:last + 1] = new
    return _join(lines)
