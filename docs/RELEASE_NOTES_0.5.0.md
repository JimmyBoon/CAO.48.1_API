# CAO 48.1 Compliance API — v0.5.0

**Date:** 26 July 2026
**Previous version:** 0.4.0

Implements the Aviation Toolbox brief of 26 July 2026 in full: the new
acclimatisation endpoint, the knock-on corrections, and the four defects.

---

## ⚠️ Breaking changes

Two changes will move numbers or reject requests that succeeded in 0.4.0. Both
were failing unsafe.

### 1. Appendix 2 early start and WOCL now use the acclimatised clock

**What changed.** Under Appendix 2, the early-start test (0500–0659) and the
WOCL determination are now assessed against acclimatised time — local time at
the location the FCM is acclimatised to, or where the state is unknown, the
location they were last acclimatised to (§6). Previously the FDP table band
used that clock but the early-start reduction used the departure point's local
time.

**Who is affected.** Only Appendix 2 requests that supply
`acclimatisation.acclimatised_time_offset_hours` with a value different from
`local_time_offset_hours`. Every other request is byte-for-byte unchanged, and
every other appendix continues to use local time at the point the FDP commences,
which is what the instrument specifies for them.

**Direction of the change.** Limits go DOWN where they were previously
over-reported. Worked example — an FCM acclimatised to Perth (UTC+8) signing on
at a UTC+0 departure point at 2130Z, which is 0530 acclimatised time, on their
fifth consecutive early start:

| | 0.4.0 | 0.5.0 |
|---|---|---|
| Table band | 0500–0559 (correct) | 0500–0559 |
| Early start detected | No — assessed at 2130 | Yes — assessed at 0530 |
| Reduction | 0.0h | **4.0h** |
| `final_max_fdp_hours` | 11.0 | **7.0** |

Any published figure for an Appendix 2 crew member signing on away from the
location they are acclimatised to, on a fourth or subsequent consecutive early
start, needs to be recomputed.

**Audit trail.** Where the two clocks differ, `calculation_notes` now states
both and says which one governed, so the change is visible in every response
rather than only in these notes.

### 2. Split-duty rest touching 2300–0529 no longer falls back to the 4-hour rule

**What changed.** Once a split-duty rest includes any part of the 2300–0529
window, the stricter regime governs: 7 continuous hours with sleeping
accommodation. A rest that touched the window but fell short of those
requirements previously fell through to the ordinary 4-hour rule and collected
the extension anyway.

**Effect.** A sub-7-hour sleeping rest, or any resting-accommodation rest,
overlapping the window now earns **no extension**. `calculation_notes` states
why. Requests that set `split_duty.overlaps_2300_0529` to false, or omit it,
are unaffected.

This reading should be confirmed against CAAP 48-01. It is the conservative
one; the previous behaviour was the permissive one.

### 3. Unknown request fields are now rejected

All request models set `extra="forbid"`. A misplaced or misspelled key now
returns a 422 naming it, rather than being silently dropped.

This is technically breaking for any caller currently sending keys the API
ignores — but that is precisely the failure this closes. The reported case was
`acclimatisation.prior_off_duty_hours`, which was discarded without comment
while the engine read the top-level `preceding_off_duty_hours`, causing callers
to under-read Appendix 2 unknown-state limits by two hours with no indication
anything was wrong.

---

## New endpoints

### `POST /calculate/acclimatisation`

Determines an FCM's state of acclimatisation at a nominated moment under §7,
from where they were last acclimatised and every FDP or off-duty period
commenced since. Returns the state, the location they are acclimatised **to**,
and the clause that produced the determination.

- Implements §7.1, §7.2, §7.3, §7.4(a), §7.4(b) and the §7.5 selection
  procedure, including the requirement to use the **greatest** displacement
  across all later locations rather than the current one.
- `acclimatised_to.utc_offset_hours` feeds directly into
  `acclimatisation.acclimatised_time_offset_hours` on `/calculate/max-fdp` and
  `/validate/fdp`.
- `adaptation.acclimatised_at_utc` answers "when do I become acclimatised?" —
  null where it cannot be determined from the supplied history, never guessed.
- Stateless. UTC offsets are taken as authoritative and no time zone database
  is consulted, which keeps daylight saving out of the calculation and honours
  §6's provision allowing an AOC holder to nominate an adjoining zone.
- A third state, **`indeterminate`**, is returned where the supplied history is
  not sufficient to reach a determination — including where it contains an
  unrecorded gap long enough to have concealed an adaptation period. This is
  deliberately distinct from the §7.3 `unknown` state, which is a determination
  with its own FDP tables. `indeterminate` must never be used for a table
  lookup.

**Documented interpretations.** §6 defines a time zone as a region differing by
1 hour "or by part of 1 hour", while Table 7.1 is indexed in whole zones. This
API reads that as: the §7.1 "less than 2 hours" test uses the raw hour
difference, so 1.5 hours is not a displacement; and Table 7.1 row selection
rounds up, so 2.5 hours selects the 3-zone row. Both are the conservative
reading in their own context. Half-hour (ACST +9:30) and quarter-hour
(NPT +5:45) offsets are supported and tested.

### `GET /limits/adaptation-table`

Table 7.1 as data, matching the existing `/limits/*` family. Static — safe to
cache or prerender.

---

## Other changes

- **Appendix 2 §3.4** — `/validate/sequence` now counts consecutive
  unknown-state FDPs and raises a violation on the fifth. Requires the new
  `acclimatisation_state` field on sequence FDP events; it defaults to
  `not_applicable`, so existing callers see no new violations until they start
  declaring it. The run is ended by an FDP declared in any other state, and
  deliberately not by a long off-duty period alone — whether an off-duty period
  is a *sufficient* adaptation period depends on displacement and direction,
  which sequence events do not carry.

- **`/validate/sequence`** now accepts `acclimatised_time_offset_hours` per FDP
  event, bringing it level with `/validate/fdp` and `/validate/roster`. Early
  start streaks within a sequence are assessed on the governing clock.

- **Appendix 2 augmented crew without an acclimatisation state** returns a 422
  naming the field, instead of a 500. Tables 5.1 and 5.2 are selected by
  acclimatisation state and there is no acclimatisation-independent augmented
  table, so the request cannot be answered. Enforced identically on
  `/calculate/max-fdp` and `/validate/fdp` from one shared validator.

- **`ValueError` from the calculation engines** now returns 422 rather than
  500, via an application-level exception handler.

- **`/guide` is generated from the Pydantic models.** Parameter lists, response
  field lists and worked examples are all derived at import time from the live
  request and response models. Editorial content — purpose, when to use, common
  mistakes — remains hand-written, because introspection cannot produce it.

  This closes the whole class of problem that produced §6.3 and §6.4, and it
  was the root cause of the brief's misdiagnosis of the acclimatised clock:
  `acclimatised_time_offset_hours` had shipped in 0.4.0 but was invisible in
  the guide, so the first integrator to look for it reported it as missing. The
  guide previously documented a removed `local_start_time_of_day_hours`
  parameter, a flat parameter set for `/calculate/min-off-duty` that had become
  nested, an acclimatisation enum value the API rejects, and a three-day
  acclimatisation rule that is not in CAO 48.1 — while omitting `adjustments[]`
  entirely.

  A regression test asserts that every documented endpoint's parameters equal
  its request model's fields exactly, so the guide cannot drift again.

- **`/health`** lists `/calculate/acclimatisation` and
  `/limits/adaptation-table`.

- **`openapi.json`** regenerated: 15 paths.

---

## Tests

334 passing, up from 258. New coverage:

- every §7 branch, with a worked case each
- every Table 7.1 row in both directions, including the "10 or more" boundary
- §7.5 selection where the greatest displacement is **not** the most recent,
  and where a small eastward hop must not override a large westward one
- the §7.4(b) reduction with none, one and several qualifying preceding
  off-duty periods, plus the home-base exclusion and both failure conditions
- half-hour and quarter-hour offsets
- local night derivation, including the 8-hour minimum
- each of the four reported defects, plus the two unsafe clock fixes
- an "existing callers unaffected" test asserting that a request without the
  acclimatised offset returns exactly what it did in 0.4.0

---

## Upgrade checklist

1. Recompute any published Appendix 2 figure for crew signing on away from the
   location they are acclimatised to on a fourth or subsequent consecutive
   early start.
2. Recompute any split-duty figure where the rest overlapped 2300–0529 and was
   under 7 hours, or used resting rather than sleeping accommodation.
3. Check for request keys the API was previously ignoring — they now 422.
   `acclimatisation.prior_off_duty_hours` is the known case; the field is the
   top-level `preceding_off_duty_hours`.
4. Re-fetch `/guide`. It is materially different and now trustworthy.
5. Consider replacing self-declared acclimatisation state with a call to
   `POST /calculate/acclimatisation`.
