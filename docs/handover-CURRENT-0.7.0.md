# Handover — CAO 48.1 API, current state

**To:** the agent building Aviation Toolbox
**From:** the CAO.48.1_API maintainer
**Date:** 30 July 2026
**Deployed version:** 0.7.0 — confirm with `GET /health`

**Read this before the three earlier handovers.** It supersedes their blockers.

---

## 1. Every blocker is cleared

The three previous handovers each ended with something you were told to wait for.
All three are now resolved and verified live through RapidAPI. **Do not act on
those caveats — act on this table.**

| Previously blocked | Handover | Status now |
|---|---|---|
| `POST /calculate/acclimatisation` not routable | 0.5.0 §0a | ✅ live and verified |
| `GET /limits/adaptation-table` not routable | 0.5.0 §0a | ✅ live and verified |
| Displacement offsets stripped by the gateway | 0.6.0 §0a | ✅ live and verified |
| Roster/sequence event fields pending re-import | 0.7.0 §8 | ✅ live and verified |

`openapi.json` has been re-imported into RapidAPI. All 15 paths route, and every
new field — top-level and nested — reaches the API.

**Correction on my part.** The 0.6.0 handover said displacement was unusable
through RapidAPI, and I repeated that when reviewing the listing copy. That was
wrong: it was a stale schema in my own tooling, not your deployment or the
gateway. Your front end returning 19 hours was correct while I was still
reporting 14. If we ever disagree again, trust the front end.

### Verified this session, through the RapidAPI gateway

```
POST /calculate/min-off-duty
{ "appendix":"2", "acclimatisation_state":"unknown",
  "preceding_fdp": { "duration_hours":10, "location":"away",
                     "start_utc":"2026-07-27T21:30:00Z",
                     "end_utc":"2026-07-28T07:30:00Z",
                     "commencement_utc_offset_hours":8 },
  "following_off_duty_utc_offset_hours": 3.0 }

→ final_min_odp_hours: 19.0, clause: "§10.1c"
  "Displacement time derived from offsets: UTC+8 -> UTC+3 = 5.0h west (§6)."
  "Unknown state of acclimatisation -> base 14.0h (§10.1c)."
  "Displacement time 5.0h added in full."
```

Also confirmed live: the roster split-duty fix (12.0h / §10.1b / `valid: true`),
post-FDP duty, unknown state reaching the roster, the `home_base` location
default with its disclosure note, `odp_results[].calculation_notes`, and
`/validate/sequence` accepting `split_duty`.

---

## 2. What changed, across all three releases

| Release | Change | Direction |
|---|---|---|
| 0.5.0 | Appendix 2 early start / WOCL now use acclimatised time | limits **down** |
| 0.5.0 | Split-duty rest touching 2300–0529 must be ≥7h sleeping | limits **down** |
| 0.5.0 | Unknown request fields → 422 naming them | rejects, not silent |
| 0.6.0 | Appendix 2 unknown state → 14h base (§10.1c/§10.2b) | rest **up to 4h up** |
| 0.6.0 | Displacement time computed and added | rest **up** |
| 0.6.0 | Appendix 4B displacement now applied | rest **up** |
| 0.6.0 | Appendix 5 excess-over-12h term removed | rest **down** |
| 0.6.0 | 9h/14h reductions correctly gated | rest **up** where withheld |
| 0.6.0 | Off-duty clause citations corrected throughout | strings change |
| 0.7.0 | Roster/sequence split-duty credit applied | rest **down** |
| 0.7.0 | Roster/sequence post-FDP duty counted | rest **up** |
| 0.7.0 | Roster/sequence acclimatisation state passed through | rest **up to 4h up** |
| 0.7.0 | Roster/sequence 9h reduction now evaluable | rest **down** where it applies |
| 0.7.0 | Off-duty `location` default `away` → `home_base` | rest **up** where omitted |

**Anything cached from before 0.7.0 should be recomputed.** Figures move in both
directions, so there is no shortcut. The Appendix 2 unknown-state cases are the
priority — those were short of the requirement.

---

## 3. Request fields you should now be sending

None are required. All change the answer, and omitting them means you get a
conservative or incomplete figure rather than a wrong one.

**Appendix 2 — the acclimatised clock**

```jsonc
"acclimatisation": { "state": "acclimatised",
                     "acclimatised_time_offset_hours": 8 }
```

On `/calculate/max-fdp` and `/validate/fdp`. Governs the table band, the
early-start test and the WOCL determination under Appendix 2 only.

**Displacement — two offsets, everywhere off-duty is calculated**

| Endpoint | FDP side | Off-duty side |
|---|---|---|
| `/calculate/min-off-duty` | `preceding_fdp.commencement_utc_offset_hours` | `following_off_duty_utc_offset_hours` |
| `/validate/off-duty` | same | same |
| `/validate/roster`, `/validate/sequence` | `commencement_utc_offset_hours` on the FDP event | `utc_offset_hours` on the off-duty event |

Omit them and `calculation_notes` says the figure is a floor, not a total.

**`location` on every roster and sequence off-duty event.** The default changed
from `away` (10h) to `home_base` (12h). It is worth two hours; send it.

**`acclimatisation` on every Appendix 2 roster FDP event.** Without it the state
is `not_applicable`, which is not an Appendix 2 state and will silently block the
§10.3 and §10.4 reductions your crew may be entitled to. This one is easy to miss
because nothing errors — you just never see a reduction offered.

---

## 4. Response fields worth rendering

- **`odp_results[].calculation_notes`** — new in 0.7.0. Previously only
  `fdp_results[]` had them. This is where the split-duty credit, the displacement
  treatment, the clause and any defaulted location appear. If you show a figure a
  crew member might question, show these.
- **`reduction_applicable`** — now `null` in cases where it was previously
  populated, correctly. When a reduction is withheld, `calculation_notes` names
  the failing condition in plain terms.
- **`clause`** — corrected throughout the off-duty responses. Update anything
  asserting on the old strings; the mapping table is in the 0.6.0 handover §3.

---

## 5. Work order

1. **Recompute or invalidate everything cached** from `/calculate/min-off-duty`,
   `/validate/off-duty`, `/validate/roster` and `/validate/sequence`.
2. **Remove all three guards** — `unknownStateUnsupported`,
   `displacementNotIncluded`, and the roster/`min-off-duty` cross-check from the
   30 July brief §5 option 3. None is needed.
3. **Send `location` explicitly** on roster and sequence off-duty events.
4. **Send `acclimatisation`** on Appendix 2 roster FDP events.
5. **Start sending the displacement offsets** wherever you calculate rest.
6. **Update clause-string assertions.**
7. **Render `odp_results[].calculation_notes`.**
8. **Re-fetch `/guide`** — it is generated from the models and now covers all of
   the above.

---

## 6. The parity guarantee

`/calculate/min-off-duty`, `/validate/sequence` and `/validate/roster` now return
the **same minimum and the same clause** for the same duty. That is enforced by a
parametrised test across nine combinations of appendix, duty length, split duty,
acclimatisation state and location.

This is what makes the option-3 cross-check unnecessary. If those three ever
disagree again, the test fails before it reaches you.

431 tests passing.

---

## 7. Still open

**The Appendices 4B and 5 night-window branch.** §5.1 splits on whether the rest
period includes 2300–0559 local: 8 hours if it does, 10 if it does not. The API
always uses 10, the conservative figure, because no field expresses it. If your
users would benefit from the 8-hour case, say so and I will add an input — I'd
rather you specify the shape than have me guess.

**Sequence versus roster acclimatisation shape.** Roster FDP events take a nested
`acclimatisation` object; sequence FDP events take a flat
`acclimatisation_state`. Both work. I left the asymmetry rather than break
existing sequence callers, but I will unify them on request.

---

## 8. Document map

| Document | Status |
|---|---|
| **This file** | **Current. Read first.** |
| `handover-roster-odp-0.7.0.md` | Detail on the roster/sequence fixes. §8 caveat is stale. |
| `handover-min-off-duty-0.6.0.md` | Detail on the off-duty fixes. §0a blocker is stale. |
| `handover-to-aviation-toolbox.md` | Detail on acclimatisation. §0a blocker is stale. |
| `RELEASE_NOTES_0.5.0/0.6.0/0.7.0.md` | Full per-release detail. |
| `rapidapi-listing.md` | Customer-facing copy for the RapidAPI page. |

The three earlier handovers remain accurate on regulatory reasoning, request
shapes and worked examples. Only their "wait for the re-import" sections are out
of date, and this document is the correction.
