# CAO 48.1 Compliance API

Validate flight crew flight and duty periods against the Australian **Civil
Aviation Order 48.1 Instrument 2019** (Compilation No. 3, F2021C01239) — an
entire roster checked in a single call, with every result tied back to the
clause that governs it.

Built by an operations and crew controller, not a generalist: the parameters,
worked examples and failure modes reflect how real rostering actually breaks.

---

## What it does

Give it a duty period, a sequence, or a whole roster and it returns a pass/fail
result with every check performed — each violation tagged with its CAO 48.1
clause reference and a remediation suggestion. Behind the endpoints sits the full
FDP logic: time-band lookups, sector-based caps, WOCL and early-start
reductions, acclimatisation and augmented-crew sub-tables, split-duty extensions,
extension provisions, minimum off-duty calculation, and rolling cumulative limits
across every window the instrument defines (168 h, 336 h, 384 h, 28, 90 and
365 days, plus recovery-block and days-off requirements).

It also **determines acclimatisation for you** under §7, rather than asking crew
to self-declare the hardest judgement in the instrument.

**Coverage** — all nine appendices:

| Appendix | Operations |
|----------|------------|
| 1 | Basic limits (single-pilot) |
| 2 | Multi-pilot, complex aircraft (WOCL, acclimatisation, augmented crew) |
| 3 | Multi-pilot, except complex |
| 4 | Any operations |
| 4A | Balloon operations |
| 4B | Medical transport & emergency service |
| 5 | Aerial work & associated flight training |
| 5A | Daylight aerial work |
| 6 | Flight training |

---

## Authentication

Every request goes through the RapidAPI proxy and needs two headers:

| Header | Value |
|--------|-------|
| `X-RapidAPI-Key` | Your RapidAPI application key |
| `X-RapidAPI-Host` | `cao-48-1-compliance.p.rapidapi.com` |

> Confirm the exact host string and base URL on the **Endpoints** tab of the
> listing — RapidAPI generates these, and the code snippets on that tab are the
> authoritative source.

---

## Quick start

Maximum permissible FDP for a 3-sector duty signing on at 0600 local under
Appendix 3:

```bash
curl -X POST \
  'https://cao-48-1-compliance.p.rapidapi.com/api/v1/cao481/calculate/max-fdp' \
  -H 'X-RapidAPI-Key: YOUR_KEY' \
  -H 'X-RapidAPI-Host: cao-48-1-compliance.p.rapidapi.com' \
  -H 'Content-Type: application/json' \
  -d '{
    "appendix": "3",
    "fdp_start_utc": "2026-07-27T22:00:00Z",
    "local_time_offset_hours": 8,
    "sectors": 3
  }'
```

Response:

```json
{
  "appendix": "3",
  "base_max_fdp_hours": 12.0,
  "adjustments": [],
  "wocl_early_start_reduction_hours": 0.0,
  "final_max_fdp_hours": 12.0,
  "max_extension_hours": 1.0,
  "absolute_max_with_extension_hours": 13.0,
  "post_split_max_hours": null,
  "flight_time_limit_hours": 10.5,
  "calculation_notes": [
    "FDP start local time: 0600 -> Table 2.1 band 0600-0659, 1-3 sectors = 12h",
    "Early start #1 of 3 allowed (assessed on local time): no reduction"
  ]
}
```

You supply the **UTC instant** plus the **local offset**; the API does the
conversion and shows its working. `final_max_fdp_hours` is the answer;
`calculation_notes` and `adjustments[]` are the audit trail.

**New to the API? Call `GET /api/v1/cao481/guide` first.** It returns a
structured document covering every endpoint's purpose, its full parameter and
response shape, a worked example and the common mistakes — enough to orient an
integration (or an LLM) before making a single compliance call. It is generated
from the API's own request and response models, so it cannot drift from what the
API actually accepts.

---

## Endpoints

**Health & reference**

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/cao481/health` | Status and feature discovery |
| GET | `/api/v1/cao481/sections` | Table of contents for CAO 48.1 |
| GET | `/api/v1/cao481/sections/{section_id}` | Full text of a section or appendix |
| GET | `/api/v1/cao481/guide` | Self-describing integration guide (start here) |

**Limits (reference data)**

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/cao481/limits/fdp-table/{appendix}` | Raw FDP lookup table |
| GET | `/api/v1/cao481/limits/cumulative/{appendix}` | Cumulative limit thresholds |
| GET | `/api/v1/cao481/limits/adaptation-table` | Table 7.1 — adaptation periods to become acclimatised |

**Calculation**

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/cao481/calculate/max-fdp` | Maximum permissible FDP for a planned duty |
| POST | `/api/v1/cao481/calculate/min-off-duty` | Minimum required off-duty period |
| POST | `/api/v1/cao481/calculate/acclimatisation` | **Determine a crew member's state of acclimatisation** under §7 |

**Validation**

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/cao481/validate/fdp` | Validate a single FDP |
| POST | `/api/v1/cao481/validate/off-duty` | Validate an off-duty period |
| POST | `/api/v1/cao481/validate/cumulative` | Check rolling-window cumulative limits |
| POST | `/api/v1/cao481/validate/sequence` | Validate an FDP/ODP sequence (WOCL, consecutive-start and unknown-state rules) |
| POST | `/api/v1/cao481/validate/roster` | **Full roster** — every FDP, ODP and rest day in one call |

`/validate/sequence` and `/validate/roster` compute each off-duty minimum with
the full context of the duty before it — split-duty credit, post-FDP duty,
acclimatisation state, displacement and the preceding rest period — so they agree
with `/calculate/min-off-duty` on the same duty rather than approximating it.

For most planning work, `calculate/max-fdp` (before a duty) and `validate/roster`
(for a whole period) are all you need. Under Appendix 2, precede them with
`calculate/acclimatisation`.

---

## Acclimatisation — the Appendix 2 trap

This is the single most common source of wrong answers, and it only affects
Appendix 2.

CAO 48.1 §6 defines **acclimatised time** as local time at the location where
the crew member *is acclimatised* — not where they sign on. Under Appendix 2 the
FDP table band, the early-start test (0500–0659) and the WOCL determination are
all read against that clock. Every other appendix uses local time at the point
the FDP commences.

So a crew member acclimatised to Perth signing on in Singapore has **two
different clocks in play**, and using the wrong one moves the limit by hours.
Supply both:

```jsonc
{
  "appendix": "2",
  "sectors": 2,
  "fdp_start_utc": "2026-07-27T21:30:00Z",
  "local_time_offset_hours": 0,            // where they sign on
  "acclimatisation": {
    "state": "acclimatised",
    "acclimatised_time_offset_hours": 8    // where they are acclimatised TO
  }
}
```

`acclimatised_time_offset_hours` defaults to `local_time_offset_hours`, which is
correct only when the two coincide. Where they differ, `calculation_notes` says
so explicitly and names both times.

**Working out the state is the hard part**, and `POST /calculate/acclimatisation`
does it. Give it where the crew member was last acclimatised and every FDP or
off-duty period since, and it returns:

- the state — `acclimatised`, `unknown`, or `indeterminate`;
- the location they are acclimatised **to**, and its UTC offset, which you feed
  straight back into `acclimatised_time_offset_hours`;
- the §7 clause that produced the determination;
- the Table 7.1 adaptation period required, the §7.4(b) reduction applied, and
  **when they become acclimatised** — the question crew actually ask.

It implements §7.1 to §7.5 in full, including the §7.5 rule that the adaptation
period is selected from the **greatest** time zone displacement since last
acclimatised, not the current location's — which is frequently not the same
thing.

There is **no three-day rule** in CAO 48.1. The test is a 2-hour local time
difference and a 36-hour threshold running from commencement of duty at the
original location. Valid states are `acclimatised`, `unknown` and
`not_applicable`.

---

## Displacement time — the off-duty trap

The companion to the acclimatisation trap above, on the rest side.

`displacement time` is defined in §6 as the difference in local time between
where an FDP commenced and where the following off-duty period is taken. Under
several appendices it is an **addend to the minimum rest**, not an optional
extra — so an answer computed without it is a floor rather than a total.

Supply two offsets and the API derives both the magnitude and the direction:

```jsonc
{
  "appendix": "2",
  "preceding_fdp": {
    "duration_hours": 10,
    "location": "away",
    "start_utc": "2026-07-27T21:30:00Z",
    "end_utc": "2026-07-28T07:30:00Z",
    "commencement_utc_offset_hours": 8.0      // where the FDP commenced
  },
  "acclimatisation_state": "unknown",
  "following_off_duty_utc_offset_hours": 3.0  // where the rest is taken
}
→ final_min_odp_hours: 19.0     // 14h base + 5h displacement, in full
```

Offsets rather than a pre-computed figure is deliberate: west and east are easy
to transpose, and transposing them **shortens** the required rest. The API works
out that a larger offset at the rest location means eastward travel, and shows
the derivation in `calculation_notes`.

**How much is added depends on the appendix and the acclimatisation state:**

| Case | Amount added | Clause |
|---|---|---|
| Appendix 2, acclimatised | excess over 3h west / 2h east | §10.1(a)(ii), §10.1(b)(ii), §10.2(a)(ii) |
| **Appendix 2, unknown state** | **the full displacement** | §10.1(c)(ii), §10.2(b)(ii) |
| Appendix 4 | excess over 3h west / 2h east | §8.1, §8.2 |
| **Appendix 4B** | **the full displacement** | §5.1(a)(iii), §5.1(b)(iii) |
| Appendices 1, 3, 4A, 5, 5A, 6 | not applicable — no displacement term | — |

Omit the offsets and you get the same answer you always did, with a note saying
the figure is a floor. Supply them and the note disappears.

The same two offsets are available on `/validate/off-duty`, and on the event
models used by `/validate/sequence` and `/validate/roster` —
`commencement_utc_offset_hours` on an FDP event, `utc_offset_hours` on an
off-duty event.

**Acclimatisation matters here too.** Under Appendix 2, §10.1(c) and §10.2(b) are
separate branches for an unknown state: the base is **14 hours** rather than 10
or 12, the home base / away distinction does not apply, and the full displacement
is added. An unknown-state FCM is also ineligible for the §10.3 and §10.4
reductions, which require an acclimatised state. Appendices 3 and 4 have no
unknown-state branch.

---

## Key concepts & common pitfalls

All documented in more detail in `/guide`:

- **Supply the UTC instant and the local offset, not a local time of day.**
  Every calculation and validation endpoint takes `fdp_start_utc` (ISO 8601 UTC)
  plus `local_time_offset_hours` as hours ahead of UTC — AEST = 10.0,
  ACST = 9.5, AWST = 8.0, IST = 5.5. Account for daylight saving yourself; the
  API deliberately performs no time zone lookups, which also lets an AOC holder
  nominate an adjoining zone in its operations manual as §6 permits.

- **Unknown fields are rejected with a 422 naming them.** On a fatigue
  calculator, silently dropping an input is more dangerous than refusing the
  request — a plausible answer computed from incomplete data is the worst
  outcome. Check the `loc` path in the error; it points at the exact key.

- **The API is stateless.** No session memory between requests. Cumulative
  checks need the history on every call — `fdp_log` or `summary` on
  `/validate/cumulative`, `prior_fdp_log` or `prior_summary` on
  `/validate/roster` — ideally covering at least the past 365 days. Short logs
  under-report the long windows.

- **`crosses_wocl` is your call.** On sequence and roster events the API does not
  derive Window of Circadian Low crossings; set the flag yourself from the local
  start and end times.

- **All timestamps are UTC ISO 8601**, e.g. `2026-03-24T22:00:00Z`.

- **Validation responses always include** a top-level `valid` boolean and a
  `violations` list; each violation carries a CAO 48.1 clause reference and a
  remediation suggestion. `/validate/roster` additionally returns per-event
  breakdowns and a flat `all_violations` list for quick scanning. Both
  `fdp_results[]` and `odp_results[]` carry `calculation_notes` — that is where
  the split-duty credit, the displacement treatment and any defaulted assumption
  show up, so render them if you show a figure a crew member might question.

- **On roster and sequence off-duty events, send `location` explicitly.**
  `away` requires 10 hours and `home_base` requires 12, so the field is worth two
  hours on the same duty. It defaults to `home_base` — the longer requirement,
  because a silent default should not be the permissive one — and the response
  says when the default was used. Do not rely on it.

- **On roster and sequence FDP events, send `acclimatisation` for Appendix 2.**
  Without it the state is `not_applicable`, which is not an Appendix 2 state and
  will block the §10.3 and §10.4 reduction provisions your crew may be entitled
  to. Use `POST /calculate/acclimatisation` to determine it.

- **A split duty affects the FOLLOWING rest as well as its own FDP.** §4.1/§3.1
  extends the FDP; §4.2/§3.2 credits the effective duty used for the next
  off-duty minimum, which can move it below the 12-hour threshold and so change
  which subclause applies. Supply `split_duty` on the FDP event and both are
  applied.

- **`calculate` and `validate` are complementary.** `calculate/max-fdp` returns
  the *limit*; `validate/fdp` returns pass/fail against actual times. For a full
  planning check, calculate the limit first, then validate the actual duty.

- **`reduction_applicable.eligible` is not permission.** It reports that the
  conditions for a reduction provision are met. Applying it remains an operator
  decision under the approved FMM. Note the 9-hour reduction is only available
  where FDP plus other duty does not exceed 10 hours, and that under Appendix 2
  both reductions require an acclimatised state.

- **Single-duty endpoints cannot see history.** Consecutive early starts,
  consecutive WOCL infringements and the Appendix 2 limit of four consecutive
  FDPs in an unknown state all depend on what came before. Either pass the
  running counts to `/validate/fdp`, or use `/validate/sequence` or
  `/validate/roster`, which track them for you.

- **Appendix 2 augmented crew requires an explicit acclimatisation state.**
  Tables 5.1 and 5.2 are selected by it and there is no
  acclimatisation-independent augmented table, so the request is rejected rather
  than guessed at.

---

## Recent changes

**v0.7.0 — roster and sequence off-duty corrections.** `/validate/roster` and
`/validate/sequence` were computing the minimum off-duty period from the FDP
duration alone, dropping five other inputs. **Figures change in both
directions**, so anything cached from these two endpoints needs recomputing:

- **A split duty now credits the following rest.** §4.2/§3.2 was being applied to
  the FDP but not to the next off-duty minimum, so a compliant roster could be
  reported as non-compliant. Figures **decrease** where a split duty precedes a
  rest period.
- **Post-FDP duty is now counted.** Duty declared in `actual_duty_time_hours`
  beyond the FDP's own duration counts towards the 12-hour threshold. Figures
  **increase**.
- **Acclimatisation state now reaches the roster.** The §10.1(c) 14-hour
  unknown-state base was corrected in 0.6.0 but could not previously reach a
  roster, so Appendix 2 rosters with unknown-state crew were up to **four hours
  short**. Figures **increase**.
- **The off-duty `location` default has changed from `away` to `home_base`** on
  roster and sequence events — 12 hours rather than 10. Send it explicitly.
  Figures **increase** where it was being omitted.
- **The 9-hour reduction can now be evaluated.** §10.3(a)/§8.3(a) need the
  preceding off-duty period, which was not being carried forward, so the
  reduction was permanently unavailable in a roster. Figures **decrease** where
  it now applies.
- **`/validate/sequence` now accepts `split_duty`**, plus `extension`,
  `augmented_crew` and `single_pilot`. Previously a sequence could not express a
  split duty at all and the request was rejected.
- **`odp_results[]` now carries `calculation_notes`**, so the off-duty working is
  visible rather than only the FDP's.

**v0.6.0 — off-duty period corrections.** Some returned figures have changed.
If you cache or publish results, please recompute:

- **Appendix 2 in an unknown state of acclimatisation now returns 14 hours**
  (§10.1(c), §10.2(b)) rather than 10 or 12. `acclimatisation_state` was
  previously accepted but not applied on this endpoint. **Figures increase by up
  to four hours** — anything previously acted on was short of the requirement.
- **Displacement time is now computed and added** when the two new offsets are
  supplied. Figures increase.
- **Appendix 5 no longer adds 1.5× the excess over 12 hours**, which §5.1 does
  not contain. A 14-hour FDP now returns 10 hours rather than 13. This is the
  only figure that decreases.
- **Appendix 4B now applies displacement time**, which was previously omitted.
- **The 9-hour and 14-hour reduction provisions are now correctly gated** — the
  9-hour one requires FDP plus other duty not exceeding 10 hours, and under
  Appendix 2 both require an acclimatised state. `reduction_applicable` will be
  null in cases where it was previously populated.
- **Clause citations corrected throughout the off-duty responses**, including
  §10.1(a) versus §10.1(b), §10.1 versus §10.2, and the reduction references
  (§10.3 and §10.4, previously cited as §10.4 and §10.5).

**v0.5.0 — acclimatisation.** Added `POST /calculate/acclimatisation` and
`GET /limits/adaptation-table`. Appendix 2 early-start and WOCL determinations
now use acclimatised time, so limits may decrease where a crew member signs on
away from the location they are acclimatised to. Unknown request fields are now
rejected with a 422 naming them rather than silently dropped.

Full detail is in the release notes; `GET /health` reports the deployed version.

---

## Disclaimer

This API is derived from CAO 48.1 Instrument 2019 and is provided as a
decision-support and reference tool only. It does not replace your operator's
approved Fatigue Management Manual (FMM), a qualified fatigue risk management
assessment, or professional regulatory advice, and it does not constitute
regulatory approval. Always verify compliance against your operator's approved
procedures and the current in-force legislation.

Where CAO 48.1 is ambiguous, the API takes the conservative reading and
documents it — see the notes on `GET /limits/adaptation-table` for the treatment
of fractional time zone displacements under §6 and Table 7.1.
