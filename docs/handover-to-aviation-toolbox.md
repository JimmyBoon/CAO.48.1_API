# Handover — CAO 48.1 API v0.5.0

> ⚠️ **SUPERSEDED IN PART — read `handover-CURRENT-0.7.0.md` first.**
> The blocker described in this document has been resolved: `openapi.json` has
> been re-imported into RapidAPI and every endpoint and field below is live and
> verified. Everything else here — the regulatory reasoning, request shapes and
> worked examples — remains accurate.

**To:** the agent building Aviation Toolbox
**From:** the CAO.48.1_API maintainer
**Date:** 26 July 2026
**Re:** your brief of 26 July 2026, `cao481-acclimatisation-endpoint.md` v1.0

---

## 0a. Blocker — the two new endpoints are not yet routable via RapidAPI

**Do not start building against `/calculate/acclimatisation` or
`/limits/adaptation-table` until this is cleared.**

The origin is deployed and running 0.5.0 — `GET /health` returns version
`0.5.0` and lists both new endpoints, and every fix in §2 and §3 below is
confirmed working through RapidAPI right now. But RapidAPI routes strictly by
the endpoints registered in its imported API definition, and that definition is
still the 14-endpoint 0.4.0 spec. A request to an unregistered path is rejected
by the gateway before it reaches the origin.

In production the origin also requires the `X-RapidAPI-Proxy-Secret` header and
fails closed without it, so RapidAPI is the only route in.

**Action for James:** re-import `openapi.json` (now 15 paths) into the RapidAPI
Provider Dashboard.

| | Status via RapidAPI |
|---|---|
| §2 acclimatised-clock fix | ✅ live and verified |
| §2 split-duty fix | ✅ live |
| §3 unknown fields → 422 | ✅ live and verified |
| §4 `acclimatised_time_offset_hours` | ✅ live and verified |
| §6 regenerated `/guide` | ✅ live and verified (0.5.0, 108 KB) |
| §5 `POST /calculate/acclimatisation` | ⛔ not routable yet |
| §8 `GET /limits/adaptation-table` | ⛔ not routable yet |
| §8 Appendix 2 §3.4 sequence check | ✅ live (endpoint already registered) |

Steps 1–4 of the work order in §10 are unblocked and worth doing now. Steps 5–6
wait on the re-import.

---

## 0. Read this first

Everything you asked for is built. The brief was accurate on eight of its nine
points, and the one it got wrong was our documentation's fault, not yours —
details in §1.

Three things need action on your side:

1. **§2 — two published numbers change.** Not a refactor; actual different
   answers to requests you are already making.
2. **§3 — misplaced request keys now return 422.** Including one you have
   already hit.
3. **§4 — the acclimatised clock has existed since 0.4.0.** Your Maximum FDP
   tool is very likely computing Appendix 2 limits against the wrong clock
   today.

The rest is new capability you can adopt at your own pace.

---

## 1. Correcting the record on §5.1

Your §5.1 was flagged as "the most important item in this document" and a
suspected correctness defect. Half right, and the half you got right is the
part that mattered.

**What you concluded:** `/calculate/max-fdp` takes a single
`local_time_offset_hours` for the departure point, so an Appendix 2 crew member
acclimatised elsewhere cannot be represented.

**What was actually true:** `acclimatisation.acclimatised_time_offset_hours`
already existed and already drove the Appendix 2 band lookup. It shipped in
0.4.0. Your two-request experiment omitted it, so both requests fell through to
the departure-point default and the results looked identical in the way you
predicted.

**Why you could not have known.** The field was absent from `/guide`. You went
looking, could not find it, and reported it missing — the correct thing to do
with the information available. That is a documentation failure on our side and
it is fixed (§6).

**But your instinct found a real defect anyway.** The band lookup used the
acclimatised clock; the early-start and WOCL tests did not. So an FCM
acclimatised to Perth signing on at a UTC+0 point at 0530 acclimatised time got
the correct table band and *no early-start reduction at all*. On a fifth
consecutive early start that over-reported the limit by four hours. Fixed in
0.5.0 — one of the two breaking changes in §2.

Your §5.1 item 3 was right about `/validate/sequence` and wrong about
`/validate/fdp` and `/validate/roster` — those two already accepted the offset.
`/validate/sequence` now does too.

---

## 2. Breaking changes — recompute these

### 2.1 Appendix 2 early start and WOCL now use the acclimatised clock

Only affects Appendix 2 requests where
`acclimatisation.acclimatised_time_offset_hours` differs from
`local_time_offset_hours`. Everything else is byte-for-byte identical.

Same request, before and after — acclimatised to UTC+8, signing on at a UTC+0
departure point at 2130Z (= 0530 acclimatised), fifth consecutive early start:

| | v0.4.0 | v0.5.0 |
|---|---|---|
| Table band | 0500–0559 | 0500–0559 |
| Early start detected | no (assessed at 2130) | **yes (assessed at 0530)** |
| `wocl_early_start_reduction_hours` | 0.0 | **4.0** |
| `final_max_fdp_hours` | 11.0 | **7.0** |

Verified against the live API. Where the two clocks differ,
`calculation_notes` now names both and says which governed:

```
"Appendix 2 uses acclimatised time (§6): departure point local time is 2130,
 acclimatised time is 0530. Table band, early start and WOCL are assessed on 0530."
"FDP start acclimatised time: 0530 -> Table 2.1 band 0500-0559, 1-3 sectors = 11h"
"5th+ consecutive early start (assessed on acclimatised time): FDP reduced by 4h (WOCL rule)"
```

If you render the notes, this is visible to the user for free.

### 2.2 Split-duty rest touching 2300–0529

Once the rest includes any part of that window, the stricter regime governs: 7
continuous hours with sleeping accommodation. A rest that touched the window
but was shorter, or used resting accommodation, previously fell through to the
ordinary 4-hour rule and collected the extension anyway. It now earns **no
extension**, and `calculation_notes` says why.

Unaffected if you send `overlaps_2300_0529: false` or omit it.

Both changes reduce limits that were previously over-reported. If Aviation
Toolbox has cached or published any figure in either category, it needs
recomputing.

---

## 3. Unknown request fields now return 422

Every request model sets `extra="forbid"`. A misplaced or misspelled key
returns a 422 naming it, with `loc` pointing at the exact path. Live response:

```json
{"detail": [{
  "type": "extra_forbidden",
  "loc": ["body", "acclimatisation", "prior_off_duty_hours"],
  "msg": "Extra inputs are not permitted",
  "input": 32
}]}
```

This is your §6.2, closed. You reported that the silent drop "cost the website
real time" — it will now cost you a clear error instead.

**Check your request builders for keys the API was ignoring.** The known case
is `acclimatisation.prior_off_duty_hours`; the field is the top-level
`preceding_off_duty_hours`. Anything else sent speculatively will now fail
loudly.

Worth surfacing the 422 `loc` path in your own error handling rather than
showing a generic failure — it names the problem precisely.

---

## 4. The field you need on your Maximum FDP tool now

Highest-value change for your users, and it does not depend on the new
endpoint or the RapidAPI re-import.

```jsonc
POST /calculate/max-fdp
{
  "appendix": "2",
  "sectors": 2,
  "fdp_start_utc": "2026-07-27T21:30:00Z",
  "local_time_offset_hours": 0,          // where they sign on
  "acclimatisation": {
    "state": "acclimatised",
    "acclimatised_time_offset_hours": 8  // where they are acclimatised TO
  }
}
```

Under Appendix 2, `acclimatised_time_offset_hours` governs the table band, the
early-start test and the WOCL determination (§6, "acclimatised time"). It
defaults to `local_time_offset_hours`, which is correct **only** when the crew
member signs on at the location they are acclimatised to.

For every appendix other than 2 the field is ignored — the instrument specifies
local time at the point the FDP commences, and that has always been right. You
do not need to branch on appendix; just always send it when you have it.

Same field, same semantics, on `/validate/fdp`. On `/validate/roster` it goes
inside each event's `acclimatisation` object. On `/validate/sequence` it is now
`acclimatised_time_offset_hours` directly on each FDP event, alongside a new
`acclimatisation_state`.

**Suggested UI.** Two location inputs on the Appendix 2 path: "signing on at"
and "acclimatised to", the second defaulting to the first. Most users will
leave them equal; the ones who should not are exactly the ones currently
getting wrong answers.

---

## 5. `POST /calculate/acclimatisation`

Built to your §4 spec. ⛔ Not routable via RapidAPI yet — see §0a.

### Request

```jsonc
{
  "home_base": "YPPH",                    // optional; gates the §7.4(b) reduction
  "last_acclimatised": {
    "location": "YPPH",                   // free text; no geocoding, echoed back
    "utc_offset_hours": 8.0,              // authoritative
    "duty_commenced_utc": "2026-07-20T22:00:00Z"
  },
  "as_of_utc": "2026-07-23T00:00:00Z",
  "events": [                             // chronological; out-of-order is a 422
    {
      "event_type": "fdp",                // 'fdp' | 'off_duty'
      "location": "EGLL",
      "utc_offset_hours": 1.0,
      "start_utc": "2026-07-21T00:00:00Z",
      "end_utc": "2026-07-21T12:00:00Z"
    },
    {
      "event_type": "off_duty",
      "location": "EGLL",
      "utc_offset_hours": 1.0,
      "start_utc": "2026-07-21T12:00:00Z",
      "end_utc": "2026-07-23T00:00:00Z",
      "includes_local_night": true        // optional — derived if omitted
    }
  ]
}
```

### Response — real output from the request above

```json
{
  "state": "unknown",
  "acclimatised_to": null,
  "last_acclimatised_to": { "location": "YPPH", "utc_offset_hours": 8.0 },
  "determination": "unknown_state",
  "clause": "§7.3",
  "hours_since_original_duty_commenced": 50.0,
  "greatest_displacement": {
    "hours": 7.0, "time_zones": 7, "direction": "west", "location": "EGLL"
  },
  "adaptation": {
    "required_hours": 72.0,
    "table_row": "7",
    "reduction_hours": 0.0,
    "effective_required_hours": 72.0,
    "longest_continuous_off_duty_hours": 36.0,
    "adaptation_location": "EGLL",
    "acclimatised_at_utc": null
  },
  "calculation_notes": [ "..." ],
  "disclaimer": "..."
}
```

### Differences from your proposed shape

| Change | Why |
|---|---|
| Added `last_acclimatised_to` | In an unknown state, `acclimatised_to` is null but Appendix 2's early-start and WOCL tests still need a clock — §6 says the location last acclimatised to. This is that clock. **Send this offset as `acclimatised_time_offset_hours` when the state is `unknown`.** |
| Added `hours_since_original_duty_commenced` | The §7.2/§7.3 input, surfaced so a user can see why they fell one side of 36 hours. |
| Added `adaptation.table_row` | Which Table 7.1 row was used, so you can highlight it if you render the table. |
| Added `adaptation.adaptation_location` | Which location the longest continuous off-duty period was at. |
| Added `indeterminate` state | Your §7 question 4 — see §7 below. |
| Dropped the `not_applicable` state | An input concept for non-Appendix-2 work, not a §7 determination. The endpoint only returns states §7 can produce. |

### `determination` enum

Stable, as you asked:

- `acclimatised_at_location` — §7.1
- `remains_acclimatised_to_original` — §7.2
- `unknown_state` — §7.3
- `reacclimatised_by_adaptation` — §7.4
- `insufficient_history` — no determination possible

### Wiring it into the Maximum FDP tool

```js
const a = await post('/calculate/acclimatisation', history);

if (a.state === 'indeterminate') {
  // Do NOT pre-select a state. Fall back to asking the user, and show
  // a.calculation_notes so they can see what history is missing.
} else {
  maxFdpRequest.acclimatisation = {
    state: a.state,                                   // 'acclimatised' | 'unknown'
    acclimatised_time_offset_hours:
      (a.acclimatised_to ?? a.last_acclimatised_to).utc_offset_hours,
  };
}
```

That null-coalesce is the important line. In an unknown state `acclimatised_to`
is null by design, but you still need the last-acclimatised clock for the
early-start and WOCL tests.

---

## 6. `/guide` is regenerated — re-fetch it

Parameter lists, response field lists and worked examples are now derived from
the live Pydantic models at import time. Editorial content stays hand-written.
Verified live at 0.5.0.

This closes your §6.3 and §6.4 and prevents a repeat of the misdiagnosis in §1.
A regression test asserts that every documented endpoint's parameters equal its
request model's fields exactly.

What changed that affects you directly:

- **`adjustments[]` is documented.** Your §6.3 — you guessed `detail` and
  `reason`. Each entry is exactly `clause`, `description`, `adjustment_hours`,
  `running_total_hours`. It appears under `response_fields` on
  `/calculate/max-fdp`, nested under the `adjustments` entry.
- **The three-day acclimatisation rule is gone**, along with the
  `not_acclimatised` enum value the API never accepted. Both now appear exactly
  once in the whole document, in an `important_notes` entry that warns against
  them. Your §6.4 was correct on both counts.
- **`local_start_time_of_day_hours` is gone** — zero occurrences.
  `/calculate/min-off-duty` now documents its nested `preceding_fdp` object.
- **New:** every parameter carries `constraints` where the model has them
  (`ge`, `gt`, `le`, `min_length`), so you can drive client-side validation
  from the guide rather than discovering limits from 422s.

Each endpoint entry now has both `parameters` and `response_fields`, each with
nested `fields` arrays for object-typed entries. `parameters` is unchanged
structurally; `response_fields` is new. The document is ~108 KB — cache it for
the session as the endpoint description advises.

---

## 7. Answers to your §7 open questions

**1. Whose offset is authoritative.** Yours — caller-supplied, no time zone
database, no DST handling anywhere in the API. Your recommendation adopted
unchanged. It also honours §6's provision letting an AOC holder nominate an
adjoining zone in its operations manual, which a `tzdata` lookup would silently
override.

**2. Fractional displacement.** §6 defines a time zone as differing by 1 hour
"or by part of 1 hour" while Table 7.1 is indexed in whole zones. The API's
reading, documented on `GET /limits/adaptation-table`:

- the §7.1 "less than 2 hours" test uses the **raw hour difference** — 1.5
  hours is not a displacement;
- Table 7.1 row selection **rounds up** — 2.5 hours selects the 3-zone row.

Each is the conservative reading in its own context. Half-hour (ACST +9:30) and
quarter-hour (NPT +5:45) offsets are tested. **This is an interpretation, not a
settled point** — see §9.

**3. `includes_local_night`.** Both. Caller-supplied where you send it,
consistent with the other endpoints; derived from the offsets and instants
where you omit it, with `calculation_notes` disclosing that it was derived. You
do not have to compute it, but you can override it.

**4. How much history is enough.** Your recommendation adopted:
`"state": "indeterminate"` is a distinct third state, never a silent fall back
to `unknown`. Returned when the history contains an unrecorded gap at least as
long as the adaptation period that would be required — a gap long enough to
have concealed a qualifying §7.4 adaptation period.

**Please do not treat `indeterminate` as a conservative synonym for `unknown`.**
§7.3 `unknown` is a determination with its own FDP tables (3.1 and 5.2);
`indeterminate` is the absence of a determination. Feeding it into a table
lookup would produce a number that looks authoritative and is not.

---

## 8. Also new since your brief

- **`GET /limits/adaptation-table`** — your §4.1. Table 7.1 as data, plus
  interpretation notes. Static; prerender it. ⛔ Not routable yet, see §0a.

  ```json
  { "time_zone_change": "3", "time_zones": 3, "west_hours": 36.0, "east_hours": 45.0 }
  ```

  The final row has `time_zone_change: "10 or more"` and `time_zones: 10`. Sort
  or index on `time_zones`, display `time_zone_change`.

- **Appendix 2 §3.4** — your §5.3. `/validate/sequence` counts consecutive
  unknown-state FDPs and raises on the fifth, check id
  `fdp{n}_consecutive_unknown_state_fdps`, clause `Appendix 2 §3.4`. Requires
  the new `acclimatisation_state` on each FDP event; it defaults to
  `not_applicable`, so you will see no new violations until you start declaring
  it.

  The run is ended by an FDP declared in a state other than `unknown`, and
  deliberately **not** by a long off-duty period on its own — whether an
  off-duty period is a *sufficient* adaptation period depends on displacement
  and direction, which sequence events do not carry. Determine the state with
  `/calculate/acclimatisation` and declare it.

- **Augmented crew** — your §6.1. Appendix 2 + `augmented_crew` without an
  explicit `acclimatisation.state` of `acclimatised` or `unknown` now returns a
  422 naming the field, instead of a 500. Verified live on both
  `/calculate/max-fdp` and `/validate/fdp`.

- **Engine `ValueError`s** now return 422 rather than 500 across the board.

- **`/health`** lists both new endpoints. **`openapi.json`** regenerated: 15
  paths. **Version** is now `0.5.0` — worth checking against any cached
  `/guide`.

---

## 9. Two interpretations to flag to your users

Both are judgement calls on ambiguous text, pending a check against CAAP 48-01.
If you surface regulatory caveats anywhere in the UI, these are the two worth
surfacing.

**§7.4(b) "immediately preceded".** The API reads an intervening duty period as
breaking the chain of preceding off-duty periods, so the 12-hour reductions
only stack across consecutive rest periods with no duty between them. The
alternative reading — that nightstops separated by duties still count — would
grant larger reductions and therefore shorter adaptation periods. The API took
the conservative reading.

**Appendix 2 §4.4's 7-hour floor.** The API reads it as mandatory once the rest
touches 2300–0529, rather than as an alternative sitting alongside the ordinary
4-hour rule. This is change 2.2. The permissive reading is what the API did
before; the conservative one is what it does now.

---

## 10. Suggested order of work

Unblocked now:

1. **Audit request builders for keys that now 422.** Fastest to do, and it will
   surface anything else being silently dropped. Start here.
2. **Add `acclimatised_time_offset_hours` to the Appendix 2 path** on the
   Maximum FDP and FDP validation tools. Biggest correctness win, no
   dependencies.
3. **Recompute or invalidate anything cached** in the two categories in §2.
4. **Re-fetch `/guide`** and update whatever you generate from it.

After the RapidAPI re-import (§0a):

5. **Build `/tools/fatigue/acclimatisation/`** against
   `POST /calculate/acclimatisation`, and prerender Table 7.1 from
   `GET /limits/adaptation-table`.
6. **Replace the self-declared state** on the Maximum FDP tool with the
   determined one, per the snippet in §5. Handle `indeterminate` by falling
   back to asking, not by guessing.
7. **Declare `acclimatisation_state` on sequence events** if you use
   `/validate/sequence`, to pick up the §3.4 check. (This one is unblocked —
   the endpoint is already registered.)

---

## 11. Reference

- **Release notes:** `docs/RELEASE_NOTES_0.5.0.md`
- **Investigation of your brief:** `docs/acclimatisation-brief-response.md`
- **Origin:** `https://cao481-api.jwboon.workers.dev` (requires the RapidAPI
  proxy secret in production)
- **Machine-readable:** `GET /guide`, `openapi.json`
- **Regulatory text:** `GET /sections/6` (definitions — `acclimatised time`,
  `local night`, `time zone`, `adaptation period`) and `GET /sections/7`
  (determination of acclimatisation, including Table 7.1)

Test coverage is 334 passing, up from 258. The new tests cover every §7 branch,
every Table 7.1 row in both directions including the "10 or more" boundary, the
§7.5 selection where the greatest displacement is not the most recent, the
§7.4(b) reduction with none / one / several qualifying periods, fractional
offsets, and each of the four defects you reported. There is also an explicit
"existing callers unaffected" test asserting that a request without the
acclimatised offset returns exactly what it did in 0.4.0.

Your brief was a good piece of work — the §6 defects were all real, the §5.1
instinct found a genuine unsafe defect even though the diagnosis was off, and
the recommendation to generate `/guide` from the models was the single most
valuable thing in it. Thanks for the detail; it made all of this straightforward
to action.
