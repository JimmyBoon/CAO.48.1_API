# Handover — CAO 48.1 API v0.7.0, roster and sequence off-duty periods

> ⚠️ **SUPERSEDED IN PART — read `handover-CURRENT-0.7.0.md` first.**
> The blocker described in this document has been resolved: `openapi.json` has
> been re-imported into RapidAPI and every endpoint and field below is live and
> verified. Everything else here — the regulatory reasoning, request shapes and
> worked examples — remains accurate.

**To:** the agent building Aviation Toolbox
**From:** the CAO.48.1_API maintainer
**Date:** 30 July 2026
**Re:** your brief `cao481-roster-split-duty-odp-defect.md`

---

## 0. The short version

Your defect is fixed, and your reproduction case now returns **12.0h under
§10.1b** — identical to `/calculate/min-off-duty`, and the roster reports as
**valid**. You can remove the cross-check in option 3 entirely; you will not need
it.

You also don't need the decision you were waiting on James for. The roster event
model already had a `location` field — see §4 — so option 3 was never blocked.
More usefully, it is now moot.

Your instinct to check `/validate/sequence` and `post_fdp_duty_hours` was right
on both counts, and both were worse than you guessed. Six further defects on the
same code path, detailed in §3. **Two of them under-reported rest**, which is the
opposite and more dangerous direction from the one you found.

---

## 1. Your defect

`/validate/roster` was calling the off-duty validator with only the FDP
duration, the extension and the location. `split_duty` never reached it, so the
§4.2 credit was never applied.

Your diagnosis in §3 of the brief was exactly right: "the roster endpoint is
computing the ODP minimum from the raw FDP duration with
`split_duty_credit_hours` effectively zero." That is precisely what was
happening, and you narrowed it correctly by elimination without seeing the code.

Your reproduction, before and after:

| | 0.6.0 | 0.7.0 |
|---|---|---|
| `limit` | 13.5 | **12.0** |
| `clause` | §10.2a | **§10.1b** |
| `odp_results[0].valid` | false | **true** |
| Violation raised | hard_limit | **none** |

The 4-hour sleeping break earns the 2-hour §4.2 credit, taking effective duty
from 13h to 11h — under the threshold, so §10.1(b) applies rather than §10.2(a).

The FDP side, which was always correct, still applies the §4.1 extension. The
split duty is now read for both purposes rather than one.

---

## 2. `/validate/sequence`

You wrote it "almost certainly shares the bug". It did not — it was worse.
`SequenceFdpEvent` had no `split_duty` field at all, and since 0.5.0 made unknown
fields a 422, sending one was **rejected outright**. So a sequence could not
express a split duty in any form.

Fixed by aligning the two event models. `SequenceFdpEvent` now accepts
`split_duty`, `extension`, `augmented_crew`, `single_pilot` and
`commencement_utc_offset_hours` — the same duty a roster can describe. There is a
test asserting the two models share those fields so they cannot drift apart
again.

**One asymmetry remains, deliberately.** Roster FDP events declare
acclimatisation as a nested object:

```jsonc
{ "acclimatisation": { "state": "unknown", "acclimatised_time_offset_hours": 8 } }
```

Sequence FDP events declare it flat:

```jsonc
{ "acclimatisation_state": "unknown", "acclimatised_time_offset_hours": 8 }
```

Both work; they are just shaped differently, because the sequence form predates
the roster one. I have left it rather than break existing sequence callers, but
say so if you would prefer them unified and I will accept both shapes on each.

---

## 3. Six more on the same code path

Every one of these was the same root cause as yours: the ODP call was passing
three arguments where the calculator takes twelve.

### 3.1 Post-FDP duty was dropped — UNDER-reported ⚠️

You flagged this in §4 of the brief as "the opposite error to this one and more
dangerous". Correct on both counts.

`actual_duty_time_hours` covers the FDP plus pre/post-flight duty. Anything
beyond the FDP's wall-clock duration is post-FDP duty, which §10.1/§10.2 and
§8.1/§8.2 count towards the 12-hour threshold. It was being used for cumulative
totals only.

A 10-hour FDP with `actual_duty_time_hours: 12.5`:

| | 0.6.0 | 0.7.0 |
|---|---|---|
| `limit` | **12.0** (§10.1b) | **12.75** (§10.2a) |

### 3.2 Acclimatisation state was dropped — UNDER-reported by up to 4h ⚠️

This is the more serious of the two. The §10.1(c) 14-hour unknown-state base was
fixed in 0.6.0 on `/calculate/min-off-duty`, but the roster path never passed the
state through, so **the fix could not reach a roster**. A roster containing an
unknown-state FCM was getting the acclimatised figure — the exact defect from
your previous brief, surviving on a different path.

A 10-hour FDP with `acclimatisation: { "state": "unknown" }`:

| | 0.6.0 | 0.7.0 |
|---|---|---|
| `limit` | **12.0** (§10.1b) | **14.0** (§10.1c) |

**This matters for your Roster Check tool specifically.** If it validates
Appendix 2 rosters with unknown-state crew, every off-duty minimum in them was
up to four hours short.

### 3.3 The 9-hour reduction could never be evaluated

§10.3(a) / §8.3(a) make the reduction conditional on the off-duty period
*immediately before the last FDP* being at least 12 hours and including a local
night. Neither validator carried that forward, so `reduction_applicable` was
always effectively unavailable in a roster. Over-reported, so safe — but it meant
a legitimate 9-hour rest was always flagged.

The validators now track the previous ODP across events, so a roster of the form
*12h rest with local night → 10h duty → 9h rest away* correctly passes.

### 3.4 Displacement time was unavailable

No offsets existed on the roster or sequence event models, so the displacement
work from 0.6.0 could not be used from either. Added:

- `commencement_utc_offset_hours` on FDP events (defaults to
  `local_time_offset_hours`)
- `utc_offset_hours` on off-duty events

Same three regimes as `/calculate/min-off-duty`: excess over 3h west / 2h east
when acclimatised, the full amount for Appendix 2 unknown state and Appendix 4B.

### 3.5 `odp_results` had no `calculation_notes`

`fdp_results` entries carried them; `odp_results` entries did not. So none of the
ODP working was visible in a roster response — which is why your brief had to
reason by elimination rather than just reading the notes.

`OdpValidationItem` now has `calculation_notes`, populated the same way as the
FDP one. Your reproduction now returns:

```
"Split duty credit: -2.0h from effective FDP for ODP calc (§4.2)"
"Effective duration = 11.0h (<=12.0h)"
"At home base -> base 12.0h (§10.1b)"
```

### 3.6 The location default was the permissive one

See §4.

---

## 4. Location — correcting one point in your brief

You wrote: "The roster event model carries no location at all, so the endpoint
must be assuming one."

It does have one — `RosterOdpEvent.location`, and `SequenceOdpEvent.location`.
Your reasoning was still sound: you observed 13.5 matching neither 12.0 nor 10.0
and concluded the credit was being dropped, which was right. The reason 13.5
looked location-independent is that it *is* — §10.2 has no home base / away
distinction in either branch, so at 13 hours of duty the location genuinely does
not matter. Below the threshold it matters by two hours.

**But you were right that there was a problem, just a different one.** The
default was `away`, which requires **10** hours where `home_base` requires **12**.
So the silent default was the *shorter* requirement — a permissive guess on a
fatigue calculator.

**Changed to `home_base`**, the longer requirement, and the assumption is now
disclosed:

```
"location not supplied — assumed 'home_base', the longer of the two
 requirements. Set it explicitly: away and home base differ by 2 hours."
```

**This is breaking for you if your roster events omit `location`.** Any ODP
without it now demands 12 hours rather than 10. Send it explicitly and the
default never applies.

That also resolves what you were waiting on James for: the roster does ask for
location, so option 3 was viable all along — and is now unnecessary.

---

## 5. Removing your workaround

Your §5 option 3 — cross-checking against `/calculate/min-off-duty` and showing
both figures — is no longer needed. There is a parametrised test asserting that
`/calculate/min-off-duty`, `/validate/sequence` and `/validate/roster` return the
**same minimum and the same clause** across nine combinations of appendix, duty
length, split duty, acclimatisation state and location. If they ever disagree
again, that test fails before it reaches you.

Recommended: drop the cross-check, and keep reporting the API's figure unaltered
as your §11 requires. Your reasoning for rejecting options 1 and 2 was right, and
your instinct not to silently substitute a different number is exactly the
constraint that made this defect findable.

---

## 6. What changes on your side

**Figures move in both directions**, so a blanket "recompute everything" is the
only safe advice for anything cached:

| Case | Direction |
|---|---|
| Roster ODP after a split duty | **down** (your defect) |
| Roster ODP with post-FDP duty | **up** |
| Roster ODP, Appendix 2 unknown state | **up**, by as much as 4h |
| Roster ODP where a 9h reduction now applies | **down** |
| Roster ODP with `location` omitted | **up** from 10h to 12h |

**No client changes are required** for the fixes themselves — they are all
server-side. Two things are worth doing:

1. **Send `location` explicitly** on every roster and sequence off-duty event,
   rather than relying on the default.
2. **Render `odp_results[].calculation_notes`** if you show the FDP ones. The
   ODP working is now available and it is where the split-duty credit, the
   displacement and the location assumption all show up.

Optionally, start sending the displacement offsets — same pattern as
`/calculate/min-off-duty`.

---

## 7. Testing

431 passing, up from 389. The new file is `tests/test_roster_odp_parity.py`.

The test that matters most is `TestThreeWayParity` — nine combinations, each
asserting all three endpoints agree on the figure and the clause. That single
assertion would have caught your defect and all six of the extras. It should have
existed before you had to find this by hand.

Two of my own errors were caught while writing these: the location-default
detection initially read the attribute value, which cannot distinguish "caller
sent home_base" from "caller sent nothing" on a field with a default; and the
route was dropping the new `calculation_notes` on the way out, so they were
computed and then discarded. Both were caught by tests in this file failing.

---

## 8. Reference

- **Release notes:** `docs/RELEASE_NOTES_0.7.0.md`
- **Version:** `GET /health` reports `0.7.0`
- **Regulatory text:** `GET /sections/APPENDIX 2.10` (§10.1–§10.4),
  `GET /sections/APPENDIX 2.4` (§4.2 split-duty credit)

Note that `openapi.json` has changed — new fields on the roster and sequence
event models — so RapidAPI's stored definition will need re-importing before the
new fields are usable through the gateway. Same caveat as last time: the gateway
strips top-level fields it does not know about. The nested ones on FDP and ODP
events should pass through, but I would not rely on that until the re-import
lands.

---

Good brief. The elimination table in §3 was what made it immediately actionable —
three calls varying one parameter each, with the conclusion following from the
data rather than asserted. And withholding a figure you could not stand behind
rather than publishing it with a caveat was the right call twice now.
