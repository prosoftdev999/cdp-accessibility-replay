"""Compare the reported accessibility facts with what the browser exposed during the session.

expected.json holds, for every audit point and node, the facts taken from the live page
through a second debugging session while the transcript was being recorded.
"""
import json
import os
import re
import stat
import unicodedata

import pytest

ARTIFACT = "/app/output/ax_audit.json"
EXPECTED = json.load(open(os.path.join(os.path.dirname(__file__), "expected.json"), encoding="utf-8"))
STATES = EXPECTED["states"]
MAX_BYTES = 20 * 1024 * 1024


def text(value):
    """Names and descriptions are compared with whitespace runs collapsed and ends trimmed."""
    if value is None:
        return ""
    assert isinstance(value, str), f"expected a string, got {value!r}"
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", value)).strip()


def state(value):
    """State values are compared as text, so true and "true" (or 2 and "2") are the same."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip().lower()


@pytest.fixture(scope="module")
def reported():
    info = os.lstat(ARTIFACT)
    assert stat.S_ISREG(info.st_mode), "the artifact must be a regular file"
    assert info.st_size <= MAX_BYTES, "the artifact is implausibly large"
    with open(ARTIFACT, encoding="utf-8") as handle:
        document = json.load(handle)
    assert isinstance(document, dict) and isinstance(document.get("points"), dict), "top level must be {\"points\": {...}}"
    return document["points"]


def facts(reported, point, node):
    """The reported record for one node, or a failure naming what is missing."""
    assert point in reported and isinstance(reported[point], dict), f"audit point {point} is missing"
    record = reported[point].get(node)
    assert isinstance(record, dict), f"{point}: node {node} is missing"
    assert isinstance(record.get("ignored"), bool), f"{point}: node {node} needs a boolean 'ignored'"
    return record


def mismatches(reported, differs):
    """Collect (point, node) pairs for which `differs` says the report is wrong."""
    wrong = []
    for point, nodes in EXPECTED["points"].items():
        for node, want in nodes.items():
            have = facts(reported, point, node)
            if differs(want, have):
                wrong.append(f"{point}:{node}")
    return wrong


def summary(wrong):
    per_point = {}
    for item in wrong:
        per_point[item.split(":")[0]] = per_point.get(item.split(":")[0], 0) + 1
    return f"{len(wrong)} wrong, by point {per_point}, first {wrong[:8]}"


def test_every_listed_node_is_reported(reported):
    """Each audit point and each of its nodes has a record with a boolean `ignored`."""
    for point, nodes in EXPECTED["points"].items():
        for node in nodes:
            facts(reported, point, node)


def test_ignored_flags(reported):
    """`ignored` matches the browser for every node."""
    wrong = mismatches(reported, lambda want, have: want["ignored"] != have["ignored"])
    assert not wrong, summary(wrong)


def both_exposed(want, have):
    return not want["ignored"] and not have["ignored"]


def test_roles(reported):
    """`role` matches for every node the browser exposed."""
    wrong = mismatches(reported, lambda want, have: both_exposed(want, have) and want["role"] != have.get("role"))
    assert not wrong, summary(wrong)


def test_names(reported):
    """`name` matches after whitespace normalisation."""
    wrong = mismatches(reported, lambda want, have: both_exposed(want, have) and text(want["name"]) != text(have.get("name")))
    assert not wrong, summary(wrong)


def test_descriptions(reported):
    """`description` matches after whitespace normalisation; absent means empty."""
    wrong = mismatches(reported, lambda want, have: both_exposed(want, have)
                       and text(want["description"]) != text(have.get("description")))
    assert not wrong, summary(wrong)


def test_states(reported):
    """The listed state properties match: same ones present, same values."""
    def differs(want, have):
        if not both_exposed(want, have):
            return False
        given = have.get("states") or {}
        assert isinstance(given, dict), "'states' must be an object"
        have_states = {k: state(v) for k, v in given.items() if k in STATES}
        return {k: state(v) for k, v in want["states"].items()} != have_states
    wrong = mismatches(reported, differs)
    assert not wrong, summary(wrong)
