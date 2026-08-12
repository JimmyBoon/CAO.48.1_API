"""
Shared base classes for request models.

The API is a fatigue calculator. The dangerous failure mode is not a rejected
request — it is an accepted one that quietly drops an input and returns a
plausible number computed from incomplete data. That happened in the field with
`acclimatisation.prior_off_duty_hours`, which Pydantic's default behaviour
discarded without comment, causing the caller to under-read the FDP limit by
two hours with no indication anything was wrong.

Every request model therefore inherits from `StrictModel`, which forbids
unknown fields. A misplaced or misspelled key becomes a 422 that names the
offending field instead of a silent omission.

Pydantic v2 merges a subclass's `model_config` with its parent's, so subclasses
can still declare their own `json_schema_extra` examples without losing the
strictness set here.
"""

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    """
    Base for all request models: rejects unknown fields with a 422.

    Response models deliberately do NOT inherit from this — they are
    constructed internally and never parsed from untrusted input.
    """

    model_config = ConfigDict(extra="forbid")
