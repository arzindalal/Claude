"""
Minimal Cradle XML import.

Cradle exports vary by template; this reader handles the common shape:

    <items>
      <item id="..." type="Requirement">
        <attribute name="title">...</attribute>
        <attribute name="text">...</attribute>
        <attribute name="ASIL">...</attribute>
        <attribute name="derives_from">PARENT-ID</attribute>
      </item>
      ...
    </items>

If your export uses a different shape, adjust _extract_attrs below — everything
else is generic.
"""

from __future__ import annotations

from pathlib import Path

from lxml import etree

from src.kb.models import ASIL, Requirement, ReqLevel
from src.kb.parsers.tabular import _ASIL_MAP, _LEVEL_MAP


def _extract_attrs(item: etree._Element) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for attr in item.findall("attribute"):
        name = (attr.get("name") or "").strip().lower().replace(" ", "_")
        if name:
            attrs[name] = (attr.text or "").strip()
    # Common alternate shapes: direct child tags like <title>...</title>
    for child in item:
        if child.tag == "attribute":
            continue
        name = child.tag.strip().lower().replace(" ", "_")
        if name not in attrs:
            attrs[name] = (child.text or "").strip()
    return attrs


def parse_cradle_xml(path: Path) -> list[Requirement]:
    tree = etree.parse(str(path))
    root = tree.getroot()
    out: list[Requirement] = []
    for item in root.iter("item"):
        item_type = (item.get("type") or "").lower()
        if item_type and "requirement" not in item_type and item_type not in _LEVEL_MAP:
            continue
        rid = item.get("id") or ""
        attrs = _extract_attrs(item)
        rid = rid or attrs.get("id", "")
        if not rid:
            continue
        level_raw = (attrs.get("level") or item_type or "system").lower()
        level = _LEVEL_MAP.get(level_raw, ReqLevel.SYSTEM)
        asil = _ASIL_MAP.get(attrs.get("asil", "").lower(), ASIL.QM)
        out.append(Requirement(
            id=rid,
            level=level,
            title=attrs.get("title") or rid,
            text=attrs.get("text") or attrs.get("description") or "",
            asil=asil,
            parent_id=attrs.get("derives_from") or attrs.get("parent_id") or None,
            source=str(path),
            tags=[],
        ))
    return out
