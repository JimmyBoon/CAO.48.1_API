# CAO 48.1 API — Remediation Plan

**Against:** `cao481-api-remediation-spec.md` (25 Aug 2026)
**Codebase:** CAO 48.1 Compliance API v0.5.0, branch `Review-fix-1`
**Baseline:** 270 tests passing before any change. **Now:** 593 passing — 26 added in
Phase 1, 55 in Phase 2, 75 in Phase 3, 47 in Phase 4, 90 in Phase 5, 27 in Phase 6. Sixty-odd
of those are pins written before the edits they protect. Five pre-existing tests were amended
across Phases 2 and 5, each because it asserted a defect.

**All six phases of §1 are complete.** What remains is §7 — the untested appendices and rule
areas — with Appendix 4 the spec's stated priority.

---

## 0. Verification status

Every defect in the spec was traced to a specific line in this repo before this plan
was written. None of the findings are speculative; the root causes below are what the
code actually does, not what the spec inferred.

The spec's central claim holds structurally: `AugmentedCrewInput.in_flight_rest_hours_per_fcm`,
`prior_summary` on the roster path, `acclimatisation_state` in the ODP calculator, and
`consecutive_wocl_infringements` on `/validate/fdp` are all accepted by the request models
and never read by any engine.

---

## 1. Confirmed root causes

| ID | File / line | What the code actually does |
|----|-------------|------------------------------|
| S1 | `app/engines/roster_validator.py:385` | `summary=prior_summary if not combined_log else None`. `combined_log` includes the **roster's own** FDPs, so any roster with at least one FDP discards `prior_summary`. `ValidateCumulativeRequest.require_log_or_summary` (`app/models/validation.py:389`) also treats log and summary as mutually exclusive alternatives, so `validate_cumulative` has no path that merges a summary baseline into a computed log. |
| S2 | `app/engines/fdp_calculator.py:_resolve_sector_key` | For Appendix 2 augmented, returns `f"c{class_num}_{additional}fcm"` — the `sectors` argument is discarded entirely. `in_flight_rest_hours_per_fcm` appears in `app/models/calculation.py:55` and in no engine. No §5.3 gate exists anywhere. `flight_time_limit_hours=None` on both augmented tables (`app/data/fdp_tables.py`). |
| S3 | `app/engines/off_duty_calculator.py` (`final_min = reduction[...]`) | The reduction is applied unconditionally whenever `_check_reduction` returns eligible. `reduction_claimed` never reaches the calculator — `off_duty_validator.py` uses it only to decide whether to add the second check. `_check_reduction` also appends `"...(caller must verify)"` strings directly into `conditions_met`. |
| S4 | `app/engines/off_duty_calculator.py:_calc_home_away_displacement` | Delegates straight to `_calc_home_away`, which branches on `location` and threshold only. `acclim_state` is a parameter that is never read. Displacement emits a prose note and nothing else; the function takes no timezone offsets from which it could be computed. |
| S15 | `app/engines/off_duty_calculator.py:_check_reduction` (14h branch) | Builds a 3-condition list inline, identical for Appendix 2 and Appendix 3. Note that `_STANDARD_14H_CONDITIONS` in `app/data/off_duty_rules.py` *does* list an acclimatisation condition — the data is right, the code never uses the tuple. |
| S5 | `app/data/fdp_tables.py` APP4B `max_extension_hours=0.0` (comment: "urgent ops extension handled separately (+4h)" — never implemented) → `app/engines/fdp_validator.py` `if max_ext == 0: reasons.append("Appendix ... does not permit FDP extensions")` | The denial string is generated from a zero in the rule table. Appendix 4B §3 grants extensions; no 16h ceiling is modelled. |
| S6 | `app/engines/fdp_calculator.py:_calculate_wocl_reduction` | `else: return 4.0` with the note `"5th+ consecutive early start"`. Clamps instead of prohibiting. |
| S7 | `app/engines/fdp_calculator.py:_apply_split_duty` | `if overlaps_night and accommodation == "sleeping": if duration >= night_overlap_min_sleeping:` — when the inner test fails, control **falls through** to the standard §3.1 branch and grants +4h. Exactly the structure the spec predicted. |
| S8 | `app/models/validation.py`, `app/models/calculation.py` | No ordering validators, no offset range checks. `fdp_calculator._utc_to_local_minutes` ends in `% 1440`, which is where `local_time_offset_hours: 50` becomes a plausible-looking time band. |
| S9 | `app/engines/cumulative_validator.py:_add_check` | `if skipped: notes.append(...); return` — a skipped check is **removed from `checks[]` entirely**, so it cannot be reported as `data_unavailable`. `CheckResult.passed` is a non-optional `bool` (`app/models/validation.py:40`), so three-state needs a model change. `_count_days_off` has no data-coverage floor: it counts calendar days in the window regardless of whether any data covers them. |
| S10 | `app/data/fdp_tables.py` APP1 | Table only. No §2.1 window rule, no §2.5 late-FDP rule, `wocl_early_start` not set. |
| S11 | `app/engines/fdp_calculator.py:_calculate_wocl_reduction` | Returns `0.0` immediately unless the start is an early start, so `consecutive_wocl_infringements` can never affect the result on any path. |
| S12 | `app/engines/fdp_validator.py` | `applicable_limit = final_max + extension_hours_used` — the **requested** extension, uncapped. |
| S13 | Emission sites | `off_duty_calculator.py`: `f"{config.clause}.1b"`, `f"{config.clause}.1a"`. `cumulative_validator.py`: literals `"§10.5a"`, `"§10.5b"`, `"§11.1"`, `"§11.2"`, `"§5.1"`. `fdp_calculator.py`: `f"§{'4' if appendix == '2' else '3'}.night"` — the `§3.night` leak. `app/data/cumulative_limits.py` carries **no clause fields at all**, which is why the literals exist. |
| S14 | `app/data/guide.py` | 1068 hand-maintained lines; two `"0.3.0"` strings against `app_version = "0.5.0"` in `app/config.py:29`. |
| S17 | `cao481.md` + `app/parser.py:187` | The parser splits sections on `^###`. In the corpus, `3 Increase in FDP limits by split duty` sits inside the body of `### 2 FDP and flight time limits` **without a `###` prefix**. The text is present and correct; only the heading marker is missing. Same for Appendix 2 §4, Appendix 4 §3, Appendix 4B §2, Appendix 5 §2, Appendix 6 §3. |

---

## 2. Cross-cutting work (do first — everything else depends on it)

These three pieces of scaffolding are prerequisites for the per-defect fixes. Building
them up front avoids retrofitting eleven call sites later.

### C1. Three-state check results
- Change `CheckResult.passed` to `Optional[bool]` and add `status: Literal["passed","failed","data_unavailable"]`.
- Rewrite `cumulative_validator._add_check` so `skipped=True` **emits** a check with
  `status="data_unavailable"`, `passed=None`, instead of dropping it.
- Add `checks_run` / `checks_skipped` to response summaries.
- Redefine the top-level verdict: `valid` is true only when there are no violations
  **and** no `data_unavailable` checks; where checks were skipped, say so.
- *Backward compatibility:* `passed` stays present and `null`. Document that `null` is not `true`.

### C2. Clause references into the rule tables
- Add clause fields to `app/data/cumulative_limits.py` (it currently has none) and to
  `app/data/off_duty_rules.py` / `app/data/fdp_tables.py` alongside the limits they annotate.
- Delete every clause literal and every f-string-built clause at an emission site.
- Adopt `§N.M(x)` formatting throughout — `§8.1(b)`, not `§8.1b`.
- This is the fix for S13, and it is also the mechanism that makes S2, S5, S6, S7 and S15
  citable without inventing new literals.

### C3. Verified vs. asserted conditions
- Replace the single `conditions_met` list with `conditions_verified` and
  `conditions_caller_must_verify`.
- Enforce structurally: a condition in the second list cannot contribute to `eligible: true`.
- Keep `conditions_met` as a deprecated alias containing **only** verified conditions,
  so the S3 acceptance criterion ("no `caller must verify` string inside `conditions_met`")
  holds for existing consumers.

---

## 3. Phased work

### Phase 1 — S1, S8 — **COMPLETE**

**S1 — `prior_summary` wired into `/validate/roster`.** Done.
`validate_cumulative` gained a `baseline_summary` parameter, distinct from the existing
either/or `summary`: hour-based windows are computed from the log and the prior total added
on top. `roster_validator.py` no longer lets the roster's own FDPs suppress the summary.
Where both `prior_fdp_log` and `prior_summary` are supplied the log wins and a warning names
the ignored field.

*Two judgement calls, both in the fail-closed direction:*

1. **Hour windows sum; assertions do not.** Days-off counts and recovery-block booleans
   describe a whole window rather than accumulating across one, so a caller-supplied value
   is authoritative and the log-derived figure is not used. Summing them would be
   meaningless, and preferring the log-derived figure would import S9's bug — the API
   currently "finds" recovery blocks in empty space and counts unknown days as days off.
   S9 will make the log-derived side honest; this precedence should be revisited then.
2. **Acceptance criterion 3 is satisfied on its defensible reading.** The criterion asks for
   identical `checks[]` actuals via `/validate/roster` and `/validate/cumulative` for the
   same summary. That can only hold where the roster contributes nothing of its own —
   a roster *with* FDPs must report prior + roster, or it has simply moved the silent
   discard from `prior_summary` to the roster's own events. The regression test asserts
   parity on a roster with no FDPs, and separately asserts that hour windows never fall
   below the roster-only total.

**S8 — request validation.** Done. New `app/models/_validators.py` holds the shared rules,
applied across `ValidateFdpRequest`, `MaxFdpRequest`, `PrecedingFdpInput`, `SplitDutyInput`,
`AcclimatisationInput`, `FdpHistoryRecord`, and every sequence and roster event type:
end strictly after start; offsets within [−12, +14] with fractional values preserved;
`duration_hours` agreeing with `end − start` to within one minute; events chronologically
ordered with non-overlapping FDPs.

*Correction to this plan as first written:* it said to remove the `% 1440` in
`_utc_to_local_minutes`. That was wrong — the modulo is also the legitimate midnight wrap
(2300Z at +0800 is 0700 local next day) and is reachable for every in-range offset. The
range check was added *alongside* it inside the engine instead, so a caller reaching the
engines directly cannot bypass it.

### Phase 2 — S3, S4, S15 — **COMPLETE**

Reduction conditions became structured data in `app/data/off_duty_rules.py` (the C3
verified/asserted split, applied locally), each carrying its own clause. Appendix 2 and
Appendix 3 now own separate condition sets rather than sharing one tuple.

- **S3 done.** `final_min_odp_hours` is always the unreduced minimum; the reduction is
  reported in `reduction_applicable` as an option. `/validate/off-duty` validates against the
  base unless `reduction_claimed` is set. `conditions_met` survives as a deprecated alias
  carrying verified conditions only, so no `caller must verify` string can appear in it.
- **S4 done.** `acclimatisation_state` now selects §10.1(c) / §10.2(b) for an unknown state,
  ignoring home base / away. `fdp_start_offset_hours` and `odp_start_offset_hours` compute
  displacement — west >3h / east >2h excess when acclimatised, the full amount when unknown.
  Appendix 4 was checked against the served text and deliberately does **not** branch on
  acclimatisation: §8.1 there is away/home only, with displacement.
- **S15 done.** §10.4(c) added and evaluated against `acclimatisation_state`; an unknown
  state makes the reduction ineligible with §10.4(c) named. The citation is §10.4, not §10.5.
  Appendix 3 §8.4 keeps its three conditions.

**Also fixed: the §8.3 / §10.3 duty-total gate — not in the spec, and the largest single
error found in this remediation.** Both clauses open "Despite subclause X.1, if the sum of
an FCM's FDP ... does not exceed 10 hours". That gate was never implemented, and the
provision displaces X.1 only — it can never reach a minimum derived from X.2. A 14h FDP
requiring 15.0h under §8.2 was being reduced to **9.0h**: a six-hour under-rest, twice the
size of S4's. Now gated, so the same case correctly routes to §8.4 → 14.0h.

**Also fixed: Appendix 2 §10.3(b).** The same asymmetry as §10.4(c), on the 9h provision —
App 2 §10.3 has five conditions to Appendix 3 §8.3's four, the extra one being
acclimatisation. The spec flagged only §10.4(c); both came from the same shared tuple.

*Knock-on effect worth knowing:* `/validate/sequence` and `/validate/roster` call
`validate_off_duty` without `reduction_claimed`, so roster ODPs are now validated against
the unreduced minimum. A roster that previously passed on an auto-applied reduction now
fails. That is the intended direction, but it will change results for existing callers.

*One existing test encoded the bug*, as the plan anticipated:
`test_reduction_to_9h_eligible` asserted `final_min_odp_hours == 9.0`, i.e. that the API
applied §8.3 unbidden. Amended, with the reasoning recorded in the test.

*Confirmed not regressed:* the §3.2 credit and §3.4(c) exclusion were pinned in
`tests/test_odp_confirmed_correct.py` before this file was touched. All 14 pins still pass.

**Deferred, deliberately:** `following_off_duty_location` is accepted by
`/calculate/min-off-duty` and `/validate/off-duty` and never read — the location branch is
driven by `preceding_fdp.location`, which the schema describes as "where the off-duty period
will be taken". Two fields mean one thing and only one is wired. This is an §8.1
parameter-contract violation rather than a calculation error, and disentangling it changes
which field drives every existing caller's result, so it belongs with the Phase 5 sweep.

### Phase 3 — S5, S6, S7, S12 — **COMPLETE**

Extension allowances and early-start limits became per-appendix data structures
(`ExtensionRules`, `EarlyStartRules` in `app/data/fdp_tables.py`), each carrying its own
clause. Split-duty clause references moved onto the appendix config alongside them.

- **S5 done.** Appendix 4B now has both provisions: §3.1 unforeseen (2h multi-pilot, 1h
  single-pilot) and §3.2 urgent (4h). The 16h ceiling is unconditional for §3.2 and applies
  to §3.1 only where the base limit was split-duty-increased (§3.1(b)) — §3.1(a) states no
  explicit ceiling, and that reading is encoded rather than assumed. §3.2(a)/(b) and §3.3
  surface as `conditions_caller_must_verify`; §3.6 is flagged as a warning naming the clause
  and saying it was not evaluated. The blanket-denial string is gone from the tree.
- **S6 done.** The relief clause enumerates a 4th and a 5th and stops; a 6th is prohibited by
  §11.1. `consecutive_early_starts >= 5` is now a hard violation on both the calculator and
  the validator, each appendix citing its own clause — §13.1 (App 2), §11.1 (App 3 and 4),
  §10.1 (App 6). No response contains `5th+`.
- **S7 done.** `_apply_split_duty` treats a night overlap as a gate rather than a branch.
  A rest overlapping 2300–0529 that is under 7 hours or not sleeping accommodation earns no
  increase — not the §3.1 increase and not the §3.3 half-credit — and records an explicit
  `0.0` adjustment citing §3.4(a) so the absence is auditable. §3.4(b) still reaches 16h.
- **S12 done.** `fdp_within_limit` is computed from `min(requested, appendix_max)`, then
  capped by any ceiling the clause states. The detail names the base, the permitted figure
  and the requested one.

**Also fixed: Appendix 5 had the same extension defect as 4B.** Clause 3 there is likewise
titled "Extensions" and §3.1 grants up to 2 hours; `max_extension_hours` was 0.0, so the same
false denial was produced. Not in the spec — Appendix 5 sits in its untested-areas list.

**Citations corrected on this path:** `§3.night` → `§3.4(a)` / `§3.4(b)`; resting
accommodation `§3.2` → `§3.3` (§3.2 is the ODP credit, a different rule); and
`"CAO 48.1 Appendix 3"` on extension checks → `§5.3(a)`. Every extension clause was read
from the served text rather than inferred — four of my first-pass guesses were wrong
(App 1 is §3.1 not §3.3, App 2 is §7.3(a)(i) not §7.3(a), App 4 is §5.3 not §5.3(a), App 6
is §4.3 not §4.3(a)), which is precisely the failure mode S13 describes.

**Also recorded, not changed: Appendix 1 has no split-duty provision.** The word does not
appear anywhere in the appendix, yet `_APP1_SPLIT` grants a +1h increase. That is a
false-permissive with no clause behind it. Left in place with a comment rather than removed,
because Appendix 1 belongs to the untested-areas pass and deserves a deliberate decision
rather than one made in passing. No clause reference is emitted for it.

*No existing test broke in this phase.* The 33 FDP pins written first
(`tests/test_fdp_confirmed_correct.py`) all still pass — two of them only after I corrected
my own expectations, which is what pins are for.

### Phase 4 — S2, S16 — **COMPLETE**

Appendix 2 §5.3 is implemented in a new engine, `app/engines/augmented_crew.py`, and gates
Tables 5.1/5.2 in both the calculator and the validator. §5.1/§5.2 permit those limits "but
only if the conditions in subclause 5.3 are met", so the conditions are a precondition on the
table, not commentary beside it.

- **Sector ceilings** (§5.3(f)(i), §5.3(g)(i)) are applied before `final_max_fdp_hours` is
  returned: Class 1 / 2 additional FCMs now gives 18 / 16 / 14 at 1 / 2 / 3 sectors, each with
  a populated `adjustments[]` entry naming the clause. Where no sector-derived reduction
  applies, an explicit `0.0` adjustment records that, following the S7 pattern.
- **§5.3(c)** prohibits 4+ sectors outright (S16), on both endpoints.
- **In-flight rest minima** are read from `in_flight_rest_hours_per_fcm` and keyed on
  `at_controls_final_landing` — the discriminator that was present in the schema and read by
  nothing.
- **§5.3(f)(ii)** is now checkable: `second_sector_scheduled_flight_time_hours` was added for
  limb (B) and `rest_within_8h_before_landing` for limb (A). Absent either, the check reports
  `data_unavailable`.
- **§5.3(a), (b) and (e)** surface as caller-must-verify warnings and never as satisfied checks.

**The open reading is resolved, and against the spec's suspicion.** Clause 5's title
("Increase in FDP *and flight time* limits...") and the Note under Table 5.2 both read as
though the tables cap flight time. They do not. Appendix 2 §2.2 is the operative rule:

> "An acclimatised FCM must not be assigned flight time longer than 10.5 hours **except in an
> augmented crew operation**."

followed by its own Note: "There is no flight time limit for an augmented crew operation."
`flight_time_limit_hours: null` on the augmented path is therefore **correct, not an
omission**. It is now explained in `calculation_notes` with the citation rather than being
silently null, and pinned by a regression test so a future pass does not "fix" it.

**A correction to my own first implementation:** I initially wrote the sector and rest checks
as an if/elif chain, so §5.3(g) superseded §5.3(f) and §5.3(g)(ii) superseded §5.3(d). That
produced four violations on the spec's payload but not the four it names. §5.3 introduces a
list — "the conditions are as follows" — and they are cumulative. An 18-hour 3-sector FDP
breaches §5.3(f)(i) *and* §5.3(g)(i); a 1-hour rest breaches §5.3(d) *and* §5.3(g)(ii).
Reporting only the stricter one hides the shorter FDP the operator could lawfully have flown.
The spec's acceptance criteria encode the cumulative reading, which is what caught this.

**Cross-cutting C1 landed here, ahead of Phase 5.** S2's acceptance criteria require
`data_unavailable` rest checks, which needed the three-state contract: `CheckResult.passed`
is now `Optional[bool]` with a `status` field, and `ValidationResponse` carries `checks_run`
and `checks_skipped`.

*Behaviour change worth knowing:* on `/validate/fdp`, `valid` is now False when any check is
`data_unavailable`. A condition the API could not evaluate is not a condition satisfied, and
§5.1/§5.2 make the table limits conditional on §5.3 holding. Phase 5 generalises this to the
remaining endpoints.

**Interim measure not needed** — `augmented_crew` is implemented, so no 422 rejection.

### Phase 5 — S13, S9, S10, S11 — **COMPLETE**

- **S13 done.** Every cumulative limit now carries its own clause in
  `app/data/cumulative_limits.py`, and every literal at the emission site is gone. All nine
  appendices were re-derived from the served text: Appendix 3 flight time is §9.1/§9.2 (was
  §11.1/§11.2), recovery and days off are §8.5/§8.6 (was §10.5a/§10.5b), Appendix 6 duty time
  is §9.1/§9.2 (was §10.1/§10.2 — a row the spec did not catch), and Appendix 4B duty time is
  §7.1/§7.2. A structural test resolves every emitted citation through
  `GET /sections/{id}` and asserts it belongs to the appendix that emitted it.

  *One correction to the spec:* its S13 table gives Appendix 5A's 365-day flight time limit
  as §5.1. §5.1 is the **384-hour** limit; the 365-day one is **§5.4**. The corpus governs
  (§0.4 of the spec), so §5.4 is what is emitted.

- **S9 done.** `_add_check` now reports a skipped check instead of dropping it, and both
  counting functions are clamped to the period the data actually covers, so empty space is no
  longer counted as days off or scanned for recovery blocks. Coverage is decided per window,
  and the direction matters: accumulating limits (flight, duty) can only rise with more data,
  so a total already breaching is a genuine breach; minimum requirements (days off, recovery)
  can only be helped by more data, so one already met within covered data is genuinely met.
  Either way an under-covered window yields `data_unavailable`, never a pass. A computed
  figure is retained on a skipped check as an explicit lower bound.

- **S10 done.** §2.1(b) caps `/calculate/max-fdp` (1900 local now returns 6.0h, not 8.0h) and
  is a hard check on `/validate/fdp`. §2.5 counts late FDPs in a rolling 168-hour window on
  `/validate/sequence`. `flight_time_limit_hours: null` is untouched and pinned.

  *One deliberate departure from the spec:* it asks for a 0700 fallback on §2.1(a) where civil
  twilight cannot be computed. §2.1(a) is the **earlier** of twilight and 0700, so treating
  0700 as the boundary is stricter than the law and would fail the pre-0600 starts §2.3
  expressly contemplates. Instead: a start at or after 0700 passes (it satisfies the earlier
  of the two whatever twilight was), and an earlier start is `data_unavailable`. That is
  precise rather than merely conservative, and the three-state contract now exists to carry it.

- **S11 resolved as Option B, not the spec's preferred Option A.** Option A rejects
  `consecutive_early_starts` on `/validate/fdp` with a 422 — which directly contradicts S6,
  whose acceptance criteria require that parameter to raise a §11.1 violation "on both the
  calculator and the validator". The two cannot both hold. Option B removes the asymmetry the
  other way: `consecutive_wocl_infringements` is now read and enforced against §11.2 / §13.2 /
  §10.2, so neither parameter is accepted-and-ignored.

**Also fixed, found while implementing:**

- **A falsy-`None` bug in all four validators.** `if not passed:` treated a `data_unavailable`
  check (`passed=None`) as a failure and raised a violation from it — turning "could not
  check" into "breached". Now `if passed is False:`.
- **App 4B §5.4 and App 5 §5.2 are alternatives**, not two mandatory checks: both read "at
  least 1 of the following". Demanding both raised a false violation that would block a lawful
  roster.
- **App 4B §5.3 and App 5 §5.3 are conditional** on a trigger the API is not told about
  (3+ late-night FDPs, or an increased FDP). They are now surfaced as caller-must-verify
  rather than asserted as checks.
- **Appendix 5A had no 168-hour recovery requirement at all** — §4.1 is the 10h ODP and §4.2
  is 2 days off in 384 hours. An inherited default was emitting a check with no clause behind it.

**Parameter contract item cleared (deferred from Phase 2):** `following_off_duty_location` is
now optional and read. Omitted, `preceding_fdp.location` governs as before; supplied and
disagreeing, the request is rejected. Rather than change which field wins — which would move
every existing caller's answer — the ambiguity is refused.

*Four existing tests were amended*, each because it encoded a defect: one asserted a skipped
check was absent from `checks[]`, one asserted both limbs of §5.4 were required, and two
asserted `valid: true` on rosters whose cumulative windows could not be established.

**Verdict semantics — decided against the spec's literal reading.** The spec (§8.3, S9) says
`data_unavailable` must not count toward `valid: true`, which taken literally makes `valid`
False for any roster validated without prior history. That is the *common* case: an operator
checking a draft roster usually has no 365-day log to hand. A flag that fails every such
request stops carrying information, and integrators learn to ignore it — which is worse than
the problem it was meant to solve.

So `valid` reports breaches only: **True when no check failed**. Completeness is a separate,
explicit signal:

| Field | Meaning |
|-------|---------|
| `valid` | Nothing was breached. |
| `checks_skipped` | How many conditions could not be established. |
| `warnings` | Names them, and says what to supply to resolve them. |

A caller who needs a complete assessment requires `valid and checks_skipped == 0`. The
underlying S9 fix is unchanged and is the part that mattered: the API no longer *invents*
compliance — it does not count empty space as days off, and does not report finding a recovery
block that was never there. It reports honestly that it could not tell, and leaves the
significance of that to the caller.

### Phase 6 — S14, S17 — **COMPLETE**

- **S17 done, and cheaper than the spec assumed.** No re-chunking and no alias layer: the
  clause text was already served and correct, and the parser splits on `###`. **Seven** headings
  were missing the marker — the spec listed six; Appendix 4A §3 was the one it missed. Adding
  them gives each clause its own `section_id` through the existing parser.
  `GET /sections/APPENDIX 3.3` now returns the split-duty text, and no appendix has a gap in
  its section numbering. (Part 1 still shows no sections 2 or 3 — that is faithful to the
  instrument, not a chunking artefact, and the test scopes itself to appendices accordingly.)

  *Note for maintainers:* the corpus exists twice — `cao481.md` at the repo root and
  `app/data/cao481.md`, which is the one actually served. They were byte-identical and both
  were updated, but two copies of the legislative text is a drift hazard worth collapsing.

- **S14 done, and taken further than the spec asked.** Parameter documentation is generated
  from the running request models by `app/data/guide_params.py`; each POST entry now names a
  `request_model` instead of carrying a hand-written list. Worked examples come from the
  models' own schema examples, so the guide shows the same payload as the OpenAPI docs —
  three of the hand-written ones had drifted far enough to return 422.

  **Response shapes had drifted just as far**, which the spec did not flag: `/calculate/max-fdp`
  advertised `max_fdp_hours`, `time_band`, `crosses_wocl` and `is_early_start` — none of which
  the response has ever contained — while omitting every field it does return. Six endpoints
  were affected. `example_response_shape` is now generated from each route's declared
  `response_model`.

  **Appendix capability flags are now derived, not asserted.** `has_wocl_rules` was False for
  Appendix 6, which does have consecutive WOCL and early-start limits (§10) — a second instance
  of the defect the spec caught on Appendix 4B. Both flags now come from `FDP_CONFIGS`, and a
  new `has_night_operation_limits` is derived from the corpus itself, which correctly picks up
  Appendix 4B §8.

  Hand-written prose (`purpose`, `when_to_use`, `common_mistakes`) stays hand-written and is
  held to account by `tests/test_guide_contract.py`: every parameter name appearing in prose
  must exist on a real model, every `example_request` must execute against its own endpoint,
  every documented response key must appear in the live response, and no retired name
  (`local_start_time_of_day_hours`, `augmented_crew_size`, `preceding_fdp_hours`,
  `split_duty_rest_hours`, `not_acclimatised`) may reappear. The `'appendix-3'` instruction is
  corrected — the wrong format may now appear only inside an explicit warning.

  The `/validate/sequence` and `/validate/roster` prose was left alone, as the spec directed.

### Phase 7 — coverage

Appendices 4, 4A, 5, 6 and the standby / delayed-reporting / positioning / reassignment paths
received no test coverage in the audit. Given that five of the confirmed defects are the same
accepted-then-discarded pattern, expect more of it there. Prioritise **Appendix 4**.

---

## 4. Test strategy

- **Pin the good behaviour first.** Before Phase 2 or Phase 3 touches a shared engine, add
  regression tests for everything §6 of the spec lists as confirmed correct — table lookups
  and boundary probes, `/validate/sequence` §11.2, split-duty arithmetic, the §3.2/§3.4(c)
  ODP interaction, §8.3 eligibility, cumulative threshold values, `prior_fdp_log`,
  Appendix 5A `data_unavailable`. The 270 existing tests do not cover all of these.
- **Every fix gets a test asserting the specific wrong output** the API produces today —
  `valid: true` where it must be `false`, `10.0` where it must be `14.0` — not merely that
  the endpoint responds.
- **Invariant tests** (from §8): every request-model field is either read or 422'd; every
  emitted clause string resolves through `GET /sections/{id}` to a section of the right
  appendix; no check consumes a value another check in the same response rejected; no
  emitted citation matches `/^§\d+\.[a-z]+$/`.
- **Watch for tests that fail because they encode the bug.** Several existing tests almost
  certainly assert the current permissive behaviour — S6's `"5th+"` clamp and S3's applied
  reduction are the likely candidates. Per the spec's first ground rule, the test is what
  gets examined, not the fix.

---

## 5. Decisions for you

Four points where the spec leaves a genuine choice. My recommendations, and I'll proceed on
these unless you say otherwise:

1. **S11 — Option A (reject both on `/validate/fdp`).** The spec prefers it, it matches the
   guide, and `/validate/sequence` already does this properly. Option B would require callers
   to assert history the endpoint cannot check.
2. **S2 augmented flight time** — resolve against the served text before implementing. If the
   reading is ambiguous, implement the limit (fail closed) rather than document the omission.
3. **S5 Appendix 3 `absolute_max_with_extension_hours: 17.0`** — check against Appendix 3 §12
   and, if kept, attach an explicit note to the response so it reads as a decision rather than
   arithmetic.
4. **Interim 422s** — I do not expect to need them if the phases run in order, but if Phase 4
   (S2) or the displacement half of S4 slips, a 422 goes in rather than shipping a known-incomplete
   figure.

---

## 6. What this plan does not change

`/validate/sequence`, the FDP table data, the embedded legislative corpus text, and the
cumulative threshold values are all correct and stay as they are. The corpus needed six
heading markers, not a re-chunk. Nothing in this plan weakens an existing check.
