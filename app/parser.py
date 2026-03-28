"""
parser.py — CAO 48.1 Legislation Parser.

Loads the CAO 48.1 markdown file at application startup and parses it
into a structured dictionary for section-level lookups.

The parser understands the document's heading hierarchy:
    ## PART X — Title          → top-level group (Part)
    ## APPENDIX X — Title      → top-level group (Appendix)
    ### N Title                 → section within a group

Lookup keys supported:
    "PART 1"         → returns the Part 1 header and all its sections listed
    "APPENDIX 3"     → returns the Appendix 3 header and all its sections listed
    "6"              → returns section 6 (Definitions) from the preamble
    "APPENDIX 3.2"   → returns section 2 from Appendix 3
    "APPENDIX 1.1"   → returns section 1 from Appendix 1
"""

import re
import logging
from pathlib import Path
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Path to the legislation markdown file (bundled with the app)
DATA_DIR = Path(__file__).parent / "data"
CAO481_PATH = DATA_DIR / "cao481.md"


@dataclass
class Section:
    """
    A single parsed section of the legislation.

    Attributes:
        id: Unique identifier for the section (e.g. "APPENDIX 3.2", "6").
        title: The section heading text (e.g. "FDP and flight time limits").
        parent_id: The parent group identifier (e.g. "APPENDIX 3", "PART 1").
        parent_title: The parent group heading text.
        text: The full body text of the section (markdown).
        section_number: The numeric section identifier within the group (e.g. "2", "10").
    """

    id: str
    title: str
    parent_id: str
    parent_title: str
    text: str
    section_number: str


@dataclass
class Group:
    """
    A top-level group (Part or Appendix) containing multiple sections.

    Attributes:
        id: Unique identifier (e.g. "PART 1", "APPENDIX 3").
        title: The group heading text (e.g. "MULTI-PILOT OPERATIONS EXCEPT COMPLEX").
        full_heading: The complete heading line (e.g. "APPENDIX 3 — MULTI-PILOT...").
        preamble: Any text between the group heading and the first section.
        sections: Ordered list of Section objects within this group.
    """

    id: str
    title: str
    full_heading: str
    preamble: str = ""
    sections: list = field(default_factory=list)


@dataclass
class Legislation:
    """
    The fully parsed CAO 48.1 legislation.

    Attributes:
        title: Document title from the H1 heading.
        preamble: Introductory text before the first Part.
        groups: Ordered list of Group objects (Parts and Appendices).
        group_index: Lookup dictionary keyed by group ID.
        section_index: Lookup dictionary keyed by section ID.
    """

    title: str = ""
    preamble: str = ""
    groups: list = field(default_factory=list)
    group_index: dict = field(default_factory=dict)
    section_index: dict = field(default_factory=dict)


def _extract_group_id(heading: str) -> tuple:
    """
    Extract the group ID and title from a ## heading line.

    Handles both Parts and Appendices, including compound IDs like "4A", "4B", "5A".

    Args:
        heading: The heading text (e.g. "APPENDIX 3 — MULTI-PILOT OPERATIONS...").

    Returns:
        Tuple of (group_id, title) e.g. ("APPENDIX 3", "MULTI-PILOT OPERATIONS...").
    """
    # Match PART or APPENDIX with their number/ID
    m = re.match(
        r"((?:PART|APPENDIX)\s+\w+)\s*[—–-]\s*(.*)",
        heading.strip(),
        re.IGNORECASE,
    )
    if m:
        group_id = m.group(1).upper().strip()
        title = m.group(2).strip()
        return group_id, title

    # Fallback — return the whole heading
    return heading.strip().upper(), heading.strip()


def _extract_section_number(heading: str) -> tuple:
    """
    Extract the section number and title from a ### heading line.

    Args:
        heading: The heading text (e.g. "2 FDP and flight time limits").

    Returns:
        Tuple of (section_number, title) e.g. ("2", "FDP and flight time limits").
    """
    m = re.match(r"(\d+\w*)\s+(.*)", heading.strip())
    if m:
        return m.group(1), m.group(2).strip()

    # Fallback
    return heading.strip(), heading.strip()


def parse_cao481(filepath: Path = CAO481_PATH) -> Legislation:
    """
    Parse the CAO 48.1 markdown file into a structured Legislation object.

    The parser splits the document at ## and ### boundaries, building
    a two-level hierarchy of groups (Parts/Appendices) and sections.
    It also constructs lookup indices for fast retrieval by ID.

    Args:
        filepath: Path to the cao481.md file.

    Returns:
        A fully populated Legislation object with group and section indices.
    """
    logger.info("Parsing CAO 48.1 from %s", filepath)

    content = filepath.read_text(encoding="utf-8")
    legislation = Legislation()

    # ─── Extract document title from H1 heading ───
    title_match = re.match(r"^#\s+(.+)$", content, re.MULTILINE)
    if title_match:
        legislation.title = title_match.group(1).strip()

    # ─── Split at ## headings (top-level groups) ───
    # This regex splits on lines starting with "## " and captures the heading
    group_splits = re.split(r"^##\s+", content, flags=re.MULTILINE)

    # First element is everything before the first ## (document preamble)
    if group_splits:
        legislation.preamble = group_splits[0].strip()

    # ─── Process each group ───
    for group_text in group_splits[1:]:
        # The first line is the heading, the rest is the body
        lines = group_text.split("\n", 1)
        heading_line = lines[0].strip()
        body = lines[1] if len(lines) > 1 else ""

        group_id, group_title = _extract_group_id(heading_line)

        group = Group(
            id=group_id,
            title=group_title,
            full_heading=heading_line,
        )

        # ─── Split the body at ### headings (sections within the group) ───
        section_splits = re.split(r"^###\s+", body, flags=re.MULTILINE)

        # First element is the preamble text before any ### sections
        if section_splits:
            group.preamble = section_splits[0].strip()

        # Process each section
        for section_text in section_splits[1:]:
            sec_lines = section_text.split("\n", 1)
            sec_heading = sec_lines[0].strip()
            sec_body = sec_lines[1].strip() if len(sec_lines) > 1 else ""

            sec_number, sec_title = _extract_section_number(sec_heading)

            # Build the section ID
            # For Parts: the section number is the ID (e.g. "6", "7", "14")
            # For Appendices: prefix with appendix ID (e.g. "APPENDIX 3.2")
            if group_id.startswith("PART"):
                section_id = sec_number
            else:
                section_id = f"{group_id}.{sec_number}"

            section = Section(
                id=section_id,
                title=sec_title,
                parent_id=group_id,
                parent_title=group_title,
                text=sec_body,
                section_number=sec_number,
            )

            group.sections.append(section)

            # Register in the section index
            legislation.section_index[section_id] = section

        # Register the group
        legislation.groups.append(group)
        legislation.group_index[group_id] = group

    logger.info(
        "Parsed %d groups, %d sections",
        len(legislation.groups),
        len(legislation.section_index),
    )

    return legislation


def get_section(legislation: Legislation, section_id: str) -> dict:
    """
    Look up a section or group by ID and return it as a dictionary.

    Supports the following lookup patterns:
        "PART 1"         → returns group with list of section titles
        "APPENDIX 3"     → returns group with list of section titles
        "6"              → returns section 6 from Parts
        "APPENDIX 3.2"   → returns section 2 from Appendix 3

    Args:
        legislation: The parsed Legislation object.
        section_id: The section identifier to look up.

    Returns:
        Dictionary with section details, or None if not found.
    """
    # Normalise the ID — uppercase, strip whitespace
    key = section_id.strip().upper()

    # ─── Try as a group ID first (PART X or APPENDIX X) ───
    if key in legislation.group_index:
        group = legislation.group_index[key]
        return {
            "section_id": group.id,
            "title": group.title,
            "full_heading": group.full_heading,
            "preamble": group.preamble if group.preamble else None,
            "sections": [
                {
                    "id": s.id,
                    "section_number": s.section_number,
                    "title": s.title,
                }
                for s in group.sections
            ],
        }

    # ─── Try as a section ID ───
    if key in legislation.section_index:
        section = legislation.section_index[key]
        return {
            "section_id": section.id,
            "title": section.title,
            "parent_id": section.parent_id,
            "parent_title": section.parent_title,
            "section_number": section.section_number,
            "text": section.text,
        }

    # ─── Not found ───
    return None


def get_table_of_contents(legislation: Legislation) -> dict:
    """
    Generate the full table of contents for the legislation.

    Returns a structured dictionary with all groups and their sections,
    suitable for the GET /sections endpoint response.

    Args:
        legislation: The parsed Legislation object.

    Returns:
        Dictionary with document title and structured contents.
    """
    contents = {
        "title": legislation.title,
        "compilation": "F2021C01239",
        "compilation_number": 3,
        "groups": [],
    }

    for group in legislation.groups:
        group_entry = {
            "id": group.id,
            "title": group.title,
            "type": "part" if group.id.startswith("PART") else "appendix",
            "sections": [
                {
                    "id": s.id,
                    "section_number": s.section_number,
                    "title": s.title,
                }
                for s in group.sections
            ],
        }
        contents["groups"].append(group_entry)

    return contents


# ─── Module-level singleton ───────────────────────────────────────────
# Parse once at import time. The legislation doesn't change at runtime.
_legislation: Legislation | None = None


def get_legislation() -> Legislation:
    """
    Return the parsed legislation singleton.

    Parses the file on first call and caches the result for
    subsequent calls. Thread-safe since Python's GIL protects
    the assignment.

    Returns:
        The parsed Legislation object.
    """
    global _legislation
    if _legislation is None:
        _legislation = parse_cao481()
    return _legislation
