# CAO 48.1 API — Remediation Plan

**Against:** `cao481-api-remediation-spec.md` (25 Aug 2026)
**Codebase:** CAO 48.1 Compliance API v0.5.0, branch `Review-fix-1`
**Baseline:** 270 tests passing before any change. **Now:** 351 passing — 26 added in
Phase 1, 55 in Phase 2 (14 of them pins written before the Phase 2 edits). One pre-existing
test was amended, because it asserted the defect.

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

### Phase 3 — S5, S6, S7, S12

- **S5:** give Appendix 4B a real extension rule set keyed on `single_pilot` and
  `extension.type` — `unforeseen` 2.0h multi / 1.0h single, `urgent` 4.0h either. The 16h
  ceiling is unconditional for §3.2 and applies to §3.1 **only** where the base limit was
  split-duty-increased (§3.1(b)); §3.1(a) carries no explicit ceiling. Delete the
  "does not permit FDP extensions" string. Add §3.6 as a cumulative cross-check, marked
  `data_unavailable` when cumulative data is absent (uses C1).
- **S6:** `consecutive_early_starts >= 5` becomes a hard violation citing §11.1 on both the
  calculator and the validator. Change the note from `"5th+"` to `"5th"`. Apply the same to
  the Appendix 2 (§13) and Appendix 6 (§10) equivalents, each with its own clause number.
- **S7:** invert the condition in `_apply_split_duty` so a night overlap is a **gate**, not a
  branch: when `overlaps_2300_0529` and (`duration < 7` or accommodation is not sleeping),
  grant no increase and record an explicit `0.0` adjustment citing §3.4(a).
- **S12:** `permitted_extension = min(requested, appendix_max)`, and compute
  `fdp_within_limit` against that. Name both figures in the `detail` string.

### Phase 4 — S2, S16 (largest effort)

Implement Appendix 2 §5.3 as a gate on Tables 5.1/5.2 in both the calculator and the validator:
sector ceilings (§5.3(f)/(g)) applied **before** `final_max_fdp_hours` is returned and surfaced
in `adjustments[]`; in-flight rest minima (§5.3(d), §5.3(g)(ii)) read from
`in_flight_rest_hours_per_fcm` and keyed on `at_controls_final_landing`; 4+ sectors prohibited.
§5.3(a), (b) and (e) are unverifiable facts — surface them as `conditions_caller_must_verify`.
Where `in_flight_rest_hours_per_fcm` is absent, the rest checks are `data_unavailable`, not passed.

**Open reading to resolve before implementing:** whether Table 5.1/5.2 caps flight time as well
as FDP. Clause 5's title and the Note under Table 5.2 both suggest yes; the tables as
implemented carry `flight_time_limit_hours=None`. Resolve against the served text, then either
implement the limit or document the omission explicitly. Do not leave it silent.

**Interim if this phase slips:** reject `augmented_crew` with a 422.

### Phase 5 — S13, S9, S10, S11

- **S13** is largely done once C2 lands; this step is verifying every row of the spec's table.
- **S9** applies C1's `data_unavailable` state to the roster and sequence paths: where a lookback
  window extends earlier than the earliest supplied datum, the check is unavailable, not passed.
  Add a data-coverage floor to `_count_days_off` so it stops counting unknown days as days off.
  Appendix 5A's existing behaviour is the reference — generalise it, do not replace it.
- **S10:** Appendix 1 §2.1(b) as a hard end-time limit, §2.1(a) on start (0700 fallback where
  civil twilight cannot be computed, with the assumption noted), §2.5 late-FDP counting as a
  sequence rule, and a §2.1(b)-derived cap in `/calculate/max-fdp`.
  Leave `flight_time_limit_hours: null` alone — that is correct for Appendix 1.
- **S11:** Option A — reject both `consecutive_wocl_infringements` and `consecutive_early_starts`
  on `/validate/fdp` with a 422 naming `/validate/sequence`. Retain both on `/calculate/max-fdp`.

### Phase 6 — S14, S17

- **S17 is much cheaper than the spec assumed.** The clause text is already served and correct;
  the corpus is simply missing `###` markers on six headings. Adding them to `cao481.md` gives
  each clause its own `section_id` through the existing parser with no re-chunking and no alias
  layer. Verify each affected appendix's section list for gaps afterwards.
- **S14:** generate `/guide` parameter documentation from the running Pydantic models. Keep
  `when_to_use` and `common_mistakes` hand-written, but add a contract test asserting every
  parameter named in the guide exists on the corresponding request model and vice versa.
  Fix the `'appendix-3'` instruction in `common_mistakes` — it actively teaches the wrong format.
  Leave the `/validate/sequence` and `/validate/roster` entries alone; they are current.

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
