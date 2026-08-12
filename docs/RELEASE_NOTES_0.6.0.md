# CAO 48.1 Compliance API — v0.6.0

**Date:** 26 July 2026
**Previous version:** 0.5.0

Off-duty period fixes. Addresses the three defects in the Aviation Toolbox brief
of 26 July 2026, plus five more found while verifying them.

**Every consumer of `/calculate/min-off-duty` or `/validate/off-duty` needs to
read §1 — published figures change, and not all in the same direction.**

---

## 1. ⚠️ Figures that change

### 1.1 Appendix 2, unknown state of acclimatisation — INCREASES by up to 4 hours

**This was the safety-critical one.** `acclimatisation_state` was accepted and
discarded, so an Appendix 2 FCM in an unknown state received the acclimatised
figure. Under-reporting a rest period is the dangerous direction: it says a crew
member may be called back earlier than the instrument allows.

§10.1(c) and §10.2(b) are **separate branches**, not modifiers on the
acclimatised ones. The base is 14 hours, the home base / away distinction does
not apply, and the **full** displacement time is added rather than only the
excess.

| FDP + other duty | State | 0.5.0 | 0.6.0 |
|---|---|---|---|
| ≤ 12h, away | acclimatised | 10.0 (§10.1a) | 10.0 (§10.1a) |
| ≤ 12h, home base | acclimatised | 12.0 (§10.1a) | 12.0 (**§10.1b**) |
| ≤ 12h, away | unknown | **10.0** | **14.0 (§10.1c)** |
| ≤ 12h, home base | unknown | **12.0** | **14.0 (§10.1c)** |
| 12.5h | acclimatised | 12.75 (§10.1b) | 12.75 (**§10.2a**) |
| 12.5h | unknown | **12.75** | **14.75 (§10.2b)** |

Appendices 3 and 4 have no unknown-state branch, so their figures are unchanged
whatever state is declared.

### 1.2 Appendix 2 and 4B with displacement supplied — INCREASES

Displacement time is now computed and added. Previously no Appendix 2 answer was
complete: the response carried a note telling the caller to add something the
API would not accept. Any figure recalculated with the new offsets present will
be the same or higher.

Requests that omit the offsets return exactly what they did in 0.5.0, with a
note saying the figure is a floor rather than a total.

### 1.3 Reductions no longer offered where the instrument does not allow them — INCREASES

Three gates were missing. Each had been offering a shorter rest than permitted:

- **§10.3 / §8.3 ten-hour ceiling.** The 9-hour reduction requires FDP plus
  other duty not exceeding 10 hours. It was offered after duties of any length.
  Measured against the figure after any split-duty credit, since §3.2 / §4.2
  apply that credit "in determining the subsequent off-duty period ... under
  clause 8 [or 10]" and the reduction subclause sits inside that clause.
- **§10.3(b).** The 9-hour reduction requires the FCM to be acclimatised at the
  commencement of ODP 2. Unknown-state crew were being offered it.
- **§10.4(c).** The 14-hour reduction requires an acclimatised commencement of
  the second FDP. Same problem.

All three are Appendix 2 specific except the ten-hour ceiling, which also
applies to Appendices 3 and 4 under §8.3. Where a reduction is withheld,
`calculation_notes` now says which condition failed.

### 1.4 Appendix 5 — DECREASES

`§5.1` is a flat 8 or 10 hours plus the §3.2 extension penalty. It contains no
excess-over-12h addend, but the engine was inheriting a default multiplier and
adding 1.5× the excess.

| FDP | 0.5.0 | 0.6.0 |
|---|---|---|
| 10h | 10.0 | 10.0 |
| 14h | **13.0** | **10.0** |
| 10h, extended 1h | 12.0 | 12.0 |

This was over-reporting — the conservative direction — but it was wrong, and it
is the only figure in this release that goes down. Appendix 4B is unaffected:
§5.1(a)(ii) there genuinely does add the excess.

### 1.5 Clause citations change on every off-duty response

Corrected, so any consumer asserting on the old strings will need updating:

| Branch | 0.5.0 | 0.6.0 |
|---|---|---|
| Appendix 2, ≤12h away | §10.1a | §10.1a |
| Appendix 2, ≤12h home base | **§10.1a** | **§10.1b** |
| Appendix 2, ≤12h unknown | §10.1a | **§10.1c** |
| Appendix 2, >12h | **§10.1b** | **§10.2a** |
| Appendix 2, >12h unknown | §10.1b | **§10.2b** |
| Appendix 2, 9h reduction | **§10.4** | **§10.3** |
| Appendix 2, 14h reduction | **§10.5** | **§10.4** |
| Appendix 3/4, ≤12h home base | **§8.1a** | **§8.1b** |
| Appendix 3/4, >12h | **§8.1b** | **§8.2** |

The reduction references were the worst of these: §10.5 is the 168-hour
cumulative recovery clause, an entirely different rule from the 14-hour
reduction it was cited for.

---

## 2. New request fields

Displacement time is derived from two UTC offsets rather than taken
pre-computed. §6 defines it as "the difference in local time between (a) the
place where an FCM commenced an FDP; and (b) the place where the FCM undertakes
an off-duty period following the FDP" — both already implicit in the request.

```jsonc
{
  "appendix": "2",
  "preceding_fdp": {
    "duration_hours": 10,
    "location": "away",
    "start_utc": "2026-07-27T21:30:00Z",
    "end_utc": "2026-07-28T07:30:00Z",
    "commencement_utc_offset_hours": 8.0     // where the FDP commenced
  },
  "acclimatisation_state": "unknown",
  "following_off_duty_utc_offset_hours": 3.0  // where the rest is taken
}
→ final_min_odp_hours: 19.0   // 14h base + 5h full displacement (§10.1c)
```

Taking offsets rather than a magnitude and a direction removes a class of caller
error: west and east are easy to transpose, and transposing them shortens the
rest. The API derives both, and `calculation_notes` shows its working.

Both fields are optional and additive. Available on `/calculate/min-off-duty`
and `/validate/off-duty`.

**Three displacement regimes**, and the differences matter:

| Case | Amount added | Clause |
|---|---|---|
| Appendix 2, acclimatised | excess over 3h west / 2h east | §10.1(a)(ii), §10.1(b)(ii), §10.2(a)(ii) |
| Appendix 2, unknown | the FULL displacement | §10.1(c)(ii), §10.2(b)(ii) |
| Appendix 4 | excess over 3h west / 2h east | §8.1, §8.2 |
| Appendix 4B | the FULL displacement | §5.1(a)(iii), §5.1(b)(iii) |
| Appendices 3, 5 and others | not applicable — no displacement term | — |

Appendix 4B's displacement was declared in the configuration but never applied
by the night-branching path, so it was silently omitted from every 4B answer.

---

## 3. Other changes

- **The "displacement may apply" note now disappears once the offsets are
  supplied**, and is reworded when they are absent to say plainly that the
  figure is a floor rather than a total.

- **`reduction_applicable.conditions_met`** now lists the duty ceiling and,
  under Appendix 2, the acclimatisation condition — previously the lists
  contained a vague "FCM acclimatised (if applicable)" that was never evaluated.

- **`/guide`** documents `acclimatisation_state` on this endpoint including that
  the unknown-state base differs, which the brief asked for specifically. A test
  asserts the description mentions the 14-hour figure rather than merely that
  the parameter exists.

- **`openapi.json`** regenerated: 15 paths, new fields included.

---

## 4. Tests

389 passing, up from 334. New coverage in
`tests/test_min_off_duty_regressions.py`:

- every cell of the brief's §1 table, asserting the figure **and** the clause
- both branches of §10.2, and that neither has a home/away distinction
- displacement in all three regimes, both directions, with half-hour and
  quarter-hour offsets, and the below-threshold case
- the note appearing and disappearing
- each reduction gate: at the ceiling, above it, with post-FDP duty counted,
  with a split-duty credit, and in an unknown state
- that Appendix 3's §8.3 has no acclimatisation condition, so its behaviour is
  unchanged
- Appendix 4B displacement applied in full with no west/east threshold
- Appendix 5 flat, with the extension penalty still applied
- `/validate/off-duty` consistency, including a claimed reduction rejected in an
  unknown state
- that Appendices 3 and 4 are unaffected by `acclimatisation_state`

One pre-existing test caught an error during this work: I initially measured the
§8.3 ten-hour ceiling against total duty rather than the figure after the
split-duty credit. `test_spec_example` failed, and re-reading §3.2 confirmed the
test was right.

---

## 5. Upgrade checklist

1. **Recompute every Appendix 2 unknown-state figure.** They increase by up to
   four hours. If any has been published or acted on, it was short.
2. **Recompute Appendix 5 figures** for duties over 12 hours. They decrease.
3. **Start sending the two displacement offsets** on Appendix 2, 4 and 4B
   requests. Without them the answer remains a floor rather than a total.
4. **Update anything asserting on clause strings** — see the table in §1.5.
5. **Re-check any workflow relying on the 9-hour or 14-hour reduction.** It may
   no longer be offered, correctly.
6. Aviation Toolbox can remove the `unknownStateUnsupported` and
   `displacementNotIncluded` guards in
   `src/pages/api/calc/min-off-duty.ts`, and the tests covering them. No client
   change is needed for the fix itself — the website already sends
   `acclimatisation_state`.
