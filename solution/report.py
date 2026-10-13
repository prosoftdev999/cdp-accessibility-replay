"""Reduce a browser AX node to the facts the audit asks for."""
from __future__ import annotations

STATES = ("checked", "pressed", "selected", "expanded", "disabled", "invalid", "required", "level", "hasPopup", "modal")


def audit_facts(ax_node):
    if ax_node["ignored"]:
        return {"ignored": True}
    properties = {p["name"]: p["value"].get("value") for p in ax_node.get("properties", [])}
    return {
        "ignored": False,
        "role": ax_node["role"]["value"],
        "name": ax_node.get("name", {}).get("value", ""),
        "description": ax_node.get("description", {}).get("value", ""),
        "states": {name: properties[name] for name in STATES if name in properties},
    }
