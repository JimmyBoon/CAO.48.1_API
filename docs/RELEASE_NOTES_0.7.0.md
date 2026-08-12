# CAO 48.1 Compliance API — v0.7.0

**Date:** 30 July 2026
**Previous version:** 0.6.0

Roster and sequence off-duty period fixes. Addresses the defect in the Aviation
Toolbox brief of 30 July 2026, plus six more found on the same code path.

**Roster and sequence off-duty figures change in both directions.** Anything
cached needs recomputing — see §1.

---

## 1. ⚠️ Figures that change

The root cause of all seven items was the same: `/validate/roster` and
`/validate/sequence` were calling the off-duty validator with three arguments
where it accepts twelve. Each dropped input changed the answer, and not all in
the same direction.

| Case | 0.6.0 | 0.7.0 | Direction |
|---|---|---|---|
| Roster ODP after a split duty (13h FDP, 4h sleeping break) | 13.5 (§10.2a) | **12.0 (§10.1b)** | down |
| Roster ODP with post-FDP duty (10h FDP, 12.5h total duty) | 12.0 (§10.1b) | **12.75 (§10.2a)** | **up** |
| Roster ODP, Appendix 2 unknown state | 12.0 (§10.1b) | **14.0 (§10.1c)** | **up, by 4h** |
| Roster ODP where a 9h reduction now applies | 10.0 | **9.0** | down |
| Roster ODP with `location` omitted | 10.0 (§10.1a) | **12.0 (§10.1b)** | **up** |

### 1.1 The reported defect — split-duty credit dropped

`split_duty` never reached the off-duty calculation, so the §4.2 / §3.2 credit
was never applied. The same response acknowledged the split duty in the FDP
result and quoted §4.1 for the extension — read for one purpose, dropped for the
other.

The credit reduces effective duty, which can move it below the 12-hour threshold
and so change which subclause applies. Over-reported, which meant **a compliant
roster was reported as non-compliant** with a `hard_limit` violation.

### 1.2 Post-FDP duty dropped — under-reported

`actual_duty_time_hours` covers the FDP plus pre/post-flight duty. Anything
beyond the FDP's wall-clock duration is post-FDP duty, which §10.1/§10.2 and
§8.1/§8.2 count towards the 12-hour threshold. It was being used for cumulative
totals only.

### 1.3 Acclimatisation state dropped — under-reported by up to four hours

The §10.1(c) / §10.2(b) 14-hour unknown-state base was fixed in 0.6.0 on
`/calculate/min-off-duty`, but the roster path never passed the state through, so
**the fix could not reach a roster**. Any Appendix 2 roster containing
unknown-state crew was receiving the acclimatised figure.

### 1.4 The location default was the permissive one

`away` requires 10 hours; `home_base` requires 12. The default was `away` — the
**shorter** requirement — so a caller omitting the field silently received the
more permissive answer.

**Changed to `home_base`**, the longer requirement, and the assumption is now
stated in `calculation_notes`:

```
"location not supplied — assumed 'home_base', the longer of the two
 requirements. Set it explicitly: away and home base differ by 2 hours."
```

**Breaking for callers who omit `location`.** Send it explicitly and the default
never applies.

### 1.5 The 9-hour reduction could never be evaluated

§10.3(a) / §8.3(a) condition the reduction on the off-duty period immediately
before the last FDP being at least 12 hours and including a local night. Neither
validator carried the previous ODP forward, so the reduction was permanently
unavailable in a roster. Over-reported, so safe — but a legitimate 9-hour rest
was always flagged.

---

## 2. `/validate/sequence` could not express a split duty at all

`SequenceFdpEvent` had no `split_duty` field, and since 0.5.0 made unknown fields
a 422, sending one was rejected outright rather than silently ignored.

`SequenceFdpEvent` now accepts `split_duty`, `extension`, `augmented_crew`,
`single_pilot` and `commencement_utc_offset_hours` — the same duty a
`RosterFdpEvent` can describe. Additive and non-breaking. A test asserts the two
models share those fields so they cannot drift apart again.

One asymmetry is retained deliberately: roster FDP events declare acclimatisation
as a nested `acclimatisation` object, sequence events as a flat
`acclimatisation_state`. Unifying them would break existing sequence callers.

---

## 3. New request fields

Displacement time is now reachable from both validators:

- **FDP events** (roster and sequence): `commencement_utc_offset_hours` — UTC
  offset where the FDP commenced. Defaults to `local_time_offset_hours`.
- **Off-duty events** (roster and sequence): `utc_offset_hours` — UTC offset
  where the rest is taken.

Together these derive displacement time per §6, with the same three regimes as
`/calculate/min-off-duty`: the excess over 3h west / 2h east when acclimatised,
the full amount for Appendix 2 unknown state and for Appendix 4B.

All optional and additive.

---

## 4. New response field

`odp_results[].calculation_notes` — `FdpValidationItem` carried
`calculation_notes` but `OdpValidationItem` did not, so the off-duty working was
invisible in a roster response. It now shows the split-duty credit, the effective
duration, the displacement treatment, the clause and any defaulted location:

```json
"calculation_notes": [
  "FDP + post-FDP duty = 13.0h",
  "Split duty credit: -2.0h from effective FDP for ODP calc (§4.2)",
  "Effective duration = 11.0h (<=12.0h)",
  "At home base -> base 12.0h (§10.1b)"
]
```

---

## 5. Tests

431 passing, up from 389. New file: `tests/test_roster_odp_parity.py`.

The significant addition is `TestThreeWayParity` — nine combinations of appendix,
duty length, split duty, acclimatisation state and location, each asserting that
`/calculate/min-off-duty`, `/validate/sequence` and `/validate/roster` return the
**same minimum and the same clause**. That one assertion would have caught the
reported defect and all six extras, and it should have existed already.

Also covered: the reported reproduction case exactly; post-FDP duty including the
defensive case where declared duty is less than the FDP duration; unknown state
on both validators and its absence on Appendix 3; the 9-hour reduction with a
qualifying, a short and a no-local-night preceding ODP; displacement in both
acclimatisation states; the location default and its disclosure; and that
`odp_results` notes are populated.

Two errors of my own were caught by these tests while writing them: the
location-default detection initially read the attribute value, which cannot
distinguish a supplied `home_base` from an omitted field on a model with a
default; and the route was dropping the new `calculation_notes` on the way out,
so they were computed and discarded.

---

## 6. Upgrade checklist

1. **Recompute any cached roster or sequence off-duty figure.** They move in both
   directions, so there is no shortcut — see the table in §1.
2. **Send `location` explicitly** on roster and sequence off-duty events. The
   default has changed from `away` to `home_base`, a two-hour difference.
3. **Pay particular attention to Appendix 2 rosters with unknown-state crew.**
   Those figures were up to four hours short.
4. **Render `odp_results[].calculation_notes`** if you display the FDP notes.
5. Optionally start sending the displacement offsets.
6. **Re-import `openapi.json` into RapidAPI.** No new paths, but the event models
   have new fields and the gateway strips what its stored definition does not
   know about.
