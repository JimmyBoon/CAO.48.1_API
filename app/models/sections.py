"""
sections.py — Pydantic response models for the regulatory content endpoints.

Models for:
    GET /sections          → TableOfContentsResponse
    GET /sections/{id}     → SectionResponse (group or individual section)
"""

from pydantic import BaseModel, Field


# ─── Table of Contents models ──────────────────────────────────────────

class SectionEntry(BaseModel):
    """A single section entry within a group (used in table of contents)."""

    id: str = Field(
        description="Section identifier for API lookups (e.g. 'APPENDIX 3.2', '6').",
        json_schema_extra={"examples": ["APPENDIX 3.2"]},
    )
    section_number: str = Field(
        description="Section number within the group (e.g. '2', '10').",
        json_schema_extra={"examples": ["2"]},
    )
    title: str = Field(
        description="Section heading text.",
        json_schema_extra={"examples": ["FDP and flight time limits"]},
    )


class GroupEntry(BaseModel):
    """A top-level group (Part or Appendix) in the table of contents."""

    id: str = Field(
        description="Group identifier for API lookups (e.g. 'PART 1', 'APPENDIX 3').",
        json_schema_extra={"examples": ["APPENDIX 3"]},
    )
    title: str = Field(
        description="Group heading text.",
        json_schema_extra={
            "examples": ["MULTI-PILOT OPERATIONS EXCEPT COMPLEX"]
        },
    )
    type: str = Field(
        description="Group type: 'part' or 'appendix'.",
        json_schema_extra={"examples": ["appendix"]},
    )
    sections: list[SectionEntry] = Field(
        description="List of sections within this group.",
    )


class TableOfContentsResponse(BaseModel):
    """
    Full table of contents for CAO 48.1.

    Lists all Parts and Appendices with their constituent sections.
    Each section includes an ID that can be used with the
    GET /sections/{section_id} endpoint.
    """

    title: str = Field(
        description="Full title of the legislation.",
        json_schema_extra={
            "examples": [
                "Civil Aviation Order 48.1 Instrument 2019 (as amended)"
            ]
        },
    )
    compilation: str = Field(
        description="Federal Register of Legislation compilation identifier.",
        json_schema_extra={"examples": ["F2021C01239"]},
    )
    compilation_number: int = Field(
        description="Compilation number of the in-force version.",
        json_schema_extra={"examples": [3]},
    )
    groups: list[GroupEntry] = Field(
        description="Ordered list of Parts and Appendices.",
    )
    disclaimer: str = Field(
        default=(
            "This output is derived from Civil Aviation Order 48.1 "
            "Instrument 2019 (Authorised Version F2021C01239, "
            "Compilation No. 3) and is provided for reference purposes "
            "only. It does not replace a qualified fatigue risk management "
            "assessment, your operator's approved Fatigue Management "
            "Manual (FMM), or professional legal/regulatory advice."
        ),
        description="Legal disclaimer.",
    )


# ─── Section detail models ─────────────────────────────────────────────

class GroupDetailResponse(BaseModel):
    """
    Response for a group-level lookup (e.g. GET /sections/APPENDIX 3).

    Returns the group heading, any preamble text, and a list of
    sections within the group.
    """

    section_id: str = Field(
        description="Group identifier.",
        json_schema_extra={"examples": ["APPENDIX 3"]},
    )
    title: str = Field(
        description="Group heading text.",
        json_schema_extra={
            "examples": ["MULTI-PILOT OPERATIONS EXCEPT COMPLEX"]
        },
    )
    full_heading: str = Field(
        description="Complete heading line as it appears in the legislation.",
        json_schema_extra={
            "examples": [
                "APPENDIX 3 — MULTI-PILOT OPERATIONS EXCEPT COMPLEX"
            ]
        },
    )
    preamble: str | None = Field(
        default=None,
        description=(
            "Introductory text before the first section, if any. "
            "Includes notes about the appendix's applicability."
        ),
    )
    sections: list[SectionEntry] = Field(
        description="List of sections within this group.",
    )
    disclaimer: str = Field(
        default=(
            "This output is derived from Civil Aviation Order 48.1 "
            "Instrument 2019 (Authorised Version F2021C01239, "
            "Compilation No. 3) and is provided for reference purposes "
            "only. It does not replace a qualified fatigue risk management "
            "assessment, your operator's approved Fatigue Management "
            "Manual (FMM), or professional legal/regulatory advice."
        ),
        description="Legal disclaimer.",
    )


class SectionDetailResponse(BaseModel):
    """
    Response for a section-level lookup (e.g. GET /sections/APPENDIX 3.2).

    Returns the section heading, its parent group, and the full body text
    of the section as markdown.
    """

    section_id: str = Field(
        description="Section identifier.",
        json_schema_extra={"examples": ["APPENDIX 3.2"]},
    )
    title: str = Field(
        description="Section heading text.",
        json_schema_extra={"examples": ["FDP and flight time limits"]},
    )
    section_number: str = Field(
        description="Section number within the group.",
        json_schema_extra={"examples": ["2"]},
    )
    parent_id: str = Field(
        description="Parent group identifier.",
        json_schema_extra={"examples": ["APPENDIX 3"]},
    )
    parent_title: str = Field(
        description="Parent group heading text.",
        json_schema_extra={
            "examples": ["MULTI-PILOT OPERATIONS EXCEPT COMPLEX"]
        },
    )
    text: str = Field(
        description="Full body text of the section in markdown format.",
    )
    disclaimer: str = Field(
        default=(
            "This output is derived from Civil Aviation Order 48.1 "
            "Instrument 2019 (Authorised Version F2021C01239, "
            "Compilation No. 3) and is provided for reference purposes "
            "only. It does not replace a qualified fatigue risk management "
            "assessment, your operator's approved Fatigue Management "
            "Manual (FMM), or professional legal/regulatory advice."
        ),
        description="Legal disclaimer.",
    )
