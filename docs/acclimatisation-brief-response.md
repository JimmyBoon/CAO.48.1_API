# Response to the acclimatisation brief

**Date:** 26 July 2026
**From:** CAO.48.1_API maintainer
**Re:** `cao481-acclimatisation-endpoint.md` v1.0
**Method:** source review of `app/` plus live calls against the deployed API

---

## Summary

| Item | Brief's claim | Finding |
|---|---|---|
| §4 new endpoint | Not implemented | **Correct.** Nothing in `app/` determines acclimatisation. Buildable as specified. |
| §5.1 wrong clock | Suspected defect | **Mostly already fixed — brief missed an existing field.** One real residual defect remains (early start / WOCL). |
| §5.2 feed state in | Enhancement | Correct, additive, low risk. |
| §5.3 4 consecutive unknown FDPs | Not implemented | **Correct.** No such counter exists. |
| §5.4 split duty 2300–0529 | Unconfirmed | **Implemented**, but with a fall-through bug and it uses the wrong clock. |
| §6.1 500 error | Defect | **Confirmed**, root cause found. |
| §6.2 silently ignored field | Defect | **Confirmed.** |
| §6.3 `adjustments[]` undocumented | Defect | **Confirmed.** |
| §6.4 guide wrong | Defect | **Confirmed, and worse than described.** |

---

## §5.1 — the acclimatised clock

### The brief is working from an incomplete picture

`acclimatisation.acclimatised_time_offset_hours` **already exists** and has been deployed
since the phase 4 work. `app/models/calculation.py:31` defines it; `app/engines/
fdp_calculator.py:57-63` uses it for Appendix 2 band selection, exactly as the brief
asks for.

Live proof — same UTC instant, departure point at UTC+0, acclimatised to UTC+8:

```
POST /calculate/max-fdp
{ "appendix":"2", "sectors":2, "fdp_start_utc":"2026-07-27T21:30:00Z",
  "local_time_offset_hours": 0,
  "acclimatisation": { "state":"acclimatised", "acclimatised_time_offset_hours": 8 } }

→ "FDP start acclimatised time: 0530 -> Table 2.1 band 0500-0559, 1-3 sectors = 11h"
   final_max_fdp_hours: 11.0
```

The band followed the *acclimatised* offset, not the departure point's, and the note
even says so. The Perth-acclimatised/Singapore-signing-on case **is** representable
today.

The brief's two-request experiment omitted the nested field, so both its requests fell
through the `is not None` guard on line 57 to the local-time default. The gate is
correctly Appendix 2 only (line 57), so the §5.1 item 4 trap is already avoided.

**Why it was missed is the actual finding:** the field is absent from `/guide`. This is
§6.4, not a calculation defect. It is a good illustration of the cost of a hand-written
guide — a shipped safety-relevant feature was invisible to the first integrator who
went looking for it.

### But there is a genuine defect underneath it

`fdp_calculator.py:95` passes **`local_minutes`**, not `lookup_minutes`, into
`_calculate_wocl_reduction`. So the table band uses acclimatised time while the
early-start test uses departure-point local time. Per §6, both must use acclimatised
time under Appendix 2.

Live proof — same request as above plus `consecutive_early_starts: 4`:

```
→ wocl_early_start_reduction_hours: 0.0, final_max_fdp_hours: 11.0
```

0530 acclimatised time is an early start. On a 5th consecutive early start the FDP
should be reduced by 4 hours to 7.0. It was not reduced at all, because 2130 at the
departure point is not an early start.

**This is the correctness defect the brief was looking for, and it fails unsafe** — it
over-reports the limit by up to 4 hours. Fix is one argument on line 95, gated so
non-Appendix-2 keeps using departure local time.

### Coverage across the other endpoints

| Endpoint | Accepts acclimatised offset? |
|---|---|
| `/calculate/max-fdp` | Yes |
| `/validate/fdp` | Yes (`routes/validate.py:77`) |
| `/validate/roster` | Yes (`roster_validator.py:213`) |
| `/validate/sequence` | **No** |

`/validate/sequence` takes only `local_time_offset_hours` and never constructs an
acclimatised offset. Brief §5.1 item 3 is right about that one and wrong about the
other two.

---

## §5.3 — consecutive unknown-state FDPs

Confirmed absent. `sequence_validator.py` counts consecutive early starts and
consecutive WOCL infringements but has no acclimatisation-state counter at all. Nothing
in the codebase implements Appendix 2 §3.4. Brief is correct; this is a clean addition
to `sequence_validator` and `roster_validator`.

---

## §5.4 — split duty across 2300–0529

Partially implemented, and there are two problems.

`fdp_tables.py:213-216` sets Appendix 2 `night_overlap_min_sleeping=7.0`,
`night_overlap_cap_hours=16.0`, `night_overlap_credit_reduction=True`, and
`off_duty_calculator.py:274` honours the credit suppression. So the substance of §4.4
is there and the brief's concern is largely answered.

Two issues:

1. **Fall-through bug.** `fdp_calculator.py:320-341` — if the rest overlaps the night
   window with sleeping accommodation but is *under* 7 hours, control falls through to
   the standard §4.1 path at line 343, which only requires 4 hours, and grants the
   extension anyway. §4.4 reads as a mandatory 7-hour floor once the window is touched,
   not an optional better deal. Worth confirming the reading against CAAP 48-01 before
   changing it, because it fails unsafe.

2. **Wrong clock again.** `overlaps_2300_0529` is a caller-supplied boolean, so which
   clock it was assessed against is invisible to the API. §4.4 keys it to acclimatised
   time. Either document the expectation explicitly or derive it from the offsets, which
   are already in the request.

---

## §6 — the four defects

**6.1 — confirmed, root cause found.** `_select_table` (`fdp_calculator.py:157-166`):
with `augmented_crew` present and state `not_applicable`, neither augmented branch
matches, so it falls to `else` and returns the plain `acclimatised` table (Table 2.1).
`_resolve_sector_key` then builds an augmented key (`c2_1fcm`), which Table 2.1 does not
have → `KeyError` → 500. Reproduced live. Fix: validate in the model that Appendix 2 +
`augmented_crew` requires an explicit `acclimatisation.state`, returning 422.

**6.2 — confirmed.** `AcclimatisationInput` has only `state` and
`acclimatised_time_offset_hours`. Pydantic v2 ignores unknown keys by default, so
`prior_off_duty_hours` is dropped without trace and the Table 3.1 row selection at
`fdp_calculator.py:216-219` falls back to the conservative `<30h` row. The brief's
table of results is accurate. Recommend `model_config = {"extra": "forbid"}` across the
request models rather than a one-off — it converts this whole class of failure into a
422 that names the offending field.

**6.3 — confirmed.** The `Adjustment` model
(`models/calculation.py:141-146`) is exactly `clause` / `description` /
`adjustment_hours` / `running_total_hours` as the brief captured. `/guide` never
describes it.

**6.4 — confirmed, and worse than the brief states.** `app/data/guide.py:357-362` gives
the three-day rule and lists `valid_values: ["acclimatised", "not_acclimatised",
"unknown"]`. The live enum is `acclimatised | unknown | not_applicable`. So the guide
advertises a value the API rejects and omits one it accepts. Line 540 repeats the same
wrong list for the validate endpoints, and line 58 repeats "not_acclimatised" again.
Nothing anywhere mentions `acclimatised_time_offset_hours`.

**The brief's recommendation to generate `/guide` from the Pydantic models is the single
highest-value item in the whole document** and should be sequenced first — it would have
prevented §6.3, §6.4, and the misdiagnosis of §5.1.

---

## Answers to the §7 open questions

1. **Whose offset is authoritative.** Agreed — caller-supplied UTC offsets, no time zone
   database. That is already the established convention (`local_time_offset_hours`,
   `acclimatised_time_offset_hours`) and it sidesteps DST and the §6 nominated-zone
   provision cleanly.

2. **Fractional displacement.** Needs a decision. §6 defines a time zone as differing by
   1 hour *or part of 1 hour*, which on a literal reading makes +9:30 vs +8:00 a
   displacement of 2 zones, not 1.5. Suggested reading, to be documented in the response
   and the guide: §7.1's "less than 2 hours" test uses the raw hour difference
   (so 1.5h → not displaced), while Table 7.1 indexing rounds the hour difference **up**
   to the next whole row (so 2.5h → the 3-zone row). Conservative in both directions.
   Worth a look at CAAP 48-01 before committing.

3. **`includes_local_night`.** Keep it caller-supplied for consistency, but derive it as
   a fallback when omitted — the request already carries the instants and the offset, so
   the 8-consecutive-hours-including-2200–0500 test is computable. Return which route was
   taken in `calculation_notes` so the caller can see it.

4. **How much history is enough.** Agreed, and the distinction matters: `unknown` is a
   §7.3 determination with its own limit tables, whereas missing history is an absence of
   a determination. Add `indeterminate` as a third state and never let it silently reach
   a limit lookup.

---

## Suggested sequence

1. **§6.4 — generate `/guide` from the models.** Do this first. Everything else is
   easier to communicate once the guide is trustworthy, and it retires §6.3 for free.
2. **§5.1 residual — early start / WOCL on the acclimatised clock.** Small, fails unsafe,
   and will move published numbers. Needs release notes.
3. **§6.1 and §6.2** — both are input-validation fixes, one afternoon together.
4. **`/validate/sequence` acclimatised offset** — brings it level with the other three.
5. **§4 — `POST /calculate/acclimatisation`** plus `GET /limits/adaptation-table`. Build
   as specified; the request/response shape in the brief is consistent with the existing
   `/calculate/*` family and I would not change it.
6. **§5.3 and §5.4** — sequence-level rules, after the endpoint exists.
7. **§5.2** — last, optional.

Items 1–4 do not depend on the new endpoint and can start immediately. Only item 2
changes an existing answer.
