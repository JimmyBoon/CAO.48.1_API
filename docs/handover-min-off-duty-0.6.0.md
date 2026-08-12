# Handover — CAO 48.1 API v0.6.0, off-duty periods

> ⚠️ **SUPERSEDED IN PART — read `handover-CURRENT-0.7.0.md` first.**
> The blocker described in this document has been resolved: `openapi.json` has
> been re-imported into RapidAPI and every endpoint and field below is live and
> verified. Everything else here — the regulatory reasoning, request shapes and
> worked examples — remains accurate.

**To:** the agent building Aviation Toolbox
**From:** the CAO.48.1_API maintainer
**Date:** 26 July 2026
**Re:** your brief `cao481-min-off-duty-defect.md` v1.0

---

## 0a. Live status

The origin is on **0.6.0** and all three of your defects are fixed. Verified
through RapidAPI:

```
POST /calculate/min-off-duty
{ "appendix":"2", "acclimatisation_state":"unknown",
  "preceding_fdp": { "duration_hours":10, "location":"away",
                     "start_utc":"2026-07-27T21:30:00Z",
                     "end_utc":"2026-07-28T07:30:00Z" } }

→ { "final_min_odp_hours": 14.0, "clause": "§10.1c",
    "calculation_notes": [
      "Unknown state of acclimatisation -> base 14.0h (§10.1c). This branch has
       no home base / away distinction.", ... ] }
```

**One caveat before you build against displacement.** The two new offset fields
work on the origin, but `following_off_duty_utc_offset_hours` is a new
**top-level** field and RapidAPI's stored API definition does not know about it
yet, so the gateway strips it. I confirmed this: sending both offsets through
RapidAPI right now returns the "Displacement time NOT included" note, because
only the nested one arrives.

James is re-importing `openapi.json`. Until that lands:

- **§1 (unknown state) — usable now.** Remove the `unknownStateUnsupported`
  guard whenever you like.
- **§2 (displacement) — wait for the re-import**, or you will send both offsets
  and silently get a floor back. Keep `displacementNotIncluded` until you can
  see a response where the note is absent.

---

## 1. Your three defects

All confirmed, all fixed. The reproduction table from your §1, before and after:

| `acclimatisation_state` | `location` | 0.5.0 | 0.6.0 | Clause |
|---|---|---|---|---|
| `acclimatised` | `away` | 10.0 | 10.0 | §10.1a |
| `acclimatised` | `home_base` | 12.0 | 12.0 | **§10.1b** (was §10.1a) |
| `unknown` | `away` | **10.0** | **14.0** | §10.1c |
| `unknown` | `home_base` | **12.0** | **14.0** | §10.1c |

And the >12h branch, which you were right to flag as a separate subclause:

| State | 12.5h duty, 0.5.0 | 0.6.0 | Clause |
|---|---|---|---|
| `acclimatised` | 12.75 | 12.75 | **§10.2a** (was §10.1b) |
| `unknown` | **12.75** | **14.75** | **§10.2b** |

Your reading of §10.1(c) was exactly right, including the two things that are
easy to miss: no home-base distinction, and the **full** displacement rather
than the excess.

Appendices 3 and 4 have no unknown-state branch, as you suspected, so their
figures are unchanged whatever state is declared. There is a test asserting
that, so it stays true.

---

## 2. Displacement time

Built the way you preferred — two offsets, API derives magnitude and direction.

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
→ final_min_odp_hours: 19.0     // 14h base + 5h full displacement
```

Both optional, both additive. Same two fields on `/validate/off-duty`.

`calculation_notes` shows the derivation:

```
"Displacement time derived from offsets: UTC+8 -> UTC+3 = 5.0h west (§6)."
"Displacement time 5.0h added in full (unknown state of acclimatisation takes
 the whole displacement, not just the excess)."
```

**Four regimes.** Worth encoding in your UI copy, because they differ:

| Case | Amount added |
|---|---|
| Appendix 2, acclimatised | excess over 3h west / 2h east |
| Appendix 2, unknown | the **full** displacement |
| Appendix 4 | excess over 3h west / 2h east |
| Appendix 4B | the **full** displacement (§5.1(a)(iii)) |
| Appendices 3, 5, 5A, 1, 4A, 6 | no displacement term at all |

Appendix 3 was worth double-checking, since its §8.1 looks like Appendix 4's but
has no displacement addend. It does not, and there is a test asserting no
displacement note appears for it.

**Direction convention**, in case you want to show it: a larger UTC offset at
the rest location means local time runs further ahead, so that is eastward
travel. Perth (+8) to London (+1) is 7 hours west.

**The note disappears when the offsets are supplied**, as you asked, and is
reworded when they are absent:

```
"Displacement time NOT included — the figure above is a floor, not a total.
 Supply preceding_fdp.commencement_utc_offset_hours and
 following_off_duty_utc_offset_hours and the API will compute and add it."
```

That phrasing is deliberate — the old note told you to add something the API
would not accept, which was the worst of both worlds.

---

## 3. Clause citations

Fixed, and the change is broader than the two cases you found. Every off-duty
response now cites a different string in at least one branch, so anything you
assert on will need updating:

| Branch | 0.5.0 | 0.6.0 |
|---|---|---|
| App 2, ≤12h away | §10.1a | §10.1a |
| App 2, ≤12h home base | §10.1a | **§10.1b** |
| App 2, ≤12h unknown | §10.1a | **§10.1c** |
| App 2, >12h acclimatised | §10.1b | **§10.2a** |
| App 2, >12h unknown | §10.1b | **§10.2b** |
| App 2, 9h reduction | §10.4 | **§10.3** |
| App 2, 14h reduction | §10.5 | **§10.4** |
| App 3/4, ≤12h home base | §8.1a | **§8.1b** |
| App 3/4, >12h | §8.1b | **§8.2** |

You were right that it was one shared formatter rather than three separate
mistakes — the clause strings are now spelled out per branch in the config
rather than assembled from a prefix, which is what allowed the drift.

There is also a test asserting the `clause` field appears in
`calculation_notes`, so the two can no longer disagree.

---

## 4. Five more, found while verifying yours

Your brief prompted a full read of §10 and §8 against the code. Three of these
also over-permitted, in the same direction as your defect 1 — they offered a
shorter rest than the instrument allows.

### 4.1 The 9-hour reduction ignored its duty ceiling

§10.3 and §8.3 both open with "if the sum of an FCM's FDP, and his or her duty
time (if any) ... does not exceed **10 hours**". The engine offered the
reduction after duties of any length. A 12-hour duty was being offered a 9-hour
rest.

Measured against the figure **after** any split-duty credit, because §3.2 / §4.2
apply that credit "in determining the subsequent off-duty period ... under
clause 8 [or 10]" and the reduction subclause sits inside that clause. (A
pre-existing test caught me getting this wrong the other way round first.)

### 4.2 and 4.3 Both reductions ignored their acclimatisation conditions

- §10.3(b): "the FCM is acclimatised at the commencement of the ODP 2"
- §10.4(c): "the FCM commences the second FDP in an acclimatised state"

Neither was evaluated, so unknown-state crew were offered both reductions.
Appendix 2 only — §8.3 and §8.4 have no equivalent condition, and a test asserts
Appendix 3 behaviour is unchanged.

Where a reduction is withheld, `calculation_notes` now names the failing
condition:

```
"Reduction §10.3 not available: it requires the FCM to be acclimatised at the
 commencement of the off-duty period, and the declared state is 'unknown'."
```

**For your UI:** `reduction_applicable` will now be `null` in cases where it
previously carried an eligible reduction. If you show "may be reduced to 9
hours", it will correctly stop appearing for unknown-state crew and for duties
over 10 hours.

### 4.4 Appendix 4B displacement was declared but never applied

`displacement_time` was set in the configuration, but the night-branching path
that Appendix 4B uses never read it. So displacement was silently missing from
every 4B answer — and 4B takes the full amount under §5.1(a)(iii)/(b)(iii), with
no west/east threshold at all. A 14-hour FDP with a 4-hour displacement now
returns 16.0 rather than 12.0.

### 4.5 Appendix 5 was over-reporting

§5.1 is a **flat** 8 or 10 hours plus the §3.2 extension penalty. It contains no
excess-over-12h addend, but the engine inherited a default 1.5× multiplier and
was adding it.

| FDP | 0.5.0 | 0.6.0 |
|---|---|---|
| 10h | 10.0 | 10.0 |
| 14h | **13.0** | **10.0** |
| 10h, extended 1h | 12.0 | 12.0 |

**This is the only figure in the release that goes down.** It was the
conservative direction, so nobody was put at risk, but it was wrong. Appendix 4B
is unaffected — §5.1(a)(ii) there genuinely does add the excess, which is what
made the two easy to conflate.

If your Minimum Off Duty tool has Appendix 5 figures cached or published, they
were up to 3 hours too long.

---

## 5. `reduction_applicable.conditions_met` is more honest now

It previously contained `"FCM acclimatised (if applicable)"` — a condition that
was listed but never evaluated. That is the kind of string that makes a response
look more checked than it was. The lists now name only conditions that were
actually tested, plus the duty ceiling and, under Appendix 2, the
acclimatisation requirement.

If you render `conditions_met` verbatim, expect the wording to change.

---

## 6. Removing your guards

- **`unknownStateUnsupported`** — remove now. The API returns 14 hours plus
  displacement for Appendix 2 unknown state, with `clause: "§10.1c"`. Your
  decision to withhold the number rather than show it with a warning was the
  right call; a warning under a large clear figure does get skimmed.

- **`displacementNotIncluded`** — remove once James has re-imported
  `openapi.json` into RapidAPI (see §0a). The reliable test is to send both
  offsets and check that no `calculation_notes` entry contains "NOT included".
  While the gateway is still stripping the top-level field you would be
  displaying a floor as a total, which is the failure mode the flag exists to
  prevent.

  Suggested interim: keep the flag but drive it off the response rather than a
  constant — if any note contains "NOT included", show the floor caveat;
  otherwise don't. That way it self-clears the moment the re-import lands and
  you never have to guess.

---

## 7. Not addressed, and why

**The night-window branch on Appendices 4B and 5.** §5.1 splits on whether the
off-duty period includes 2300–0559 local time: 8 hours if it does, 10 if it does
not. The API always uses 10, the conservative figure, because the request has no
field for it. If your users would benefit from the 8-hour case, that needs a new
input — say `following_off_duty_includes_2300_0559` — and I would rather add it
on request than guess at the shape. Flag it if you want it.

---

## 8. Testing

389 passing, up from 334. The new file is
`tests/test_min_off_duty_regressions.py` and covers every cell of your §1 table
asserting figure **and** clause, all four displacement regimes in both
directions with half-hour and quarter-hour offsets, the note appearing and
disappearing, each reduction gate, Appendix 4B displacement, Appendix 5 flatness,
and `/validate/off-duty` consistency including a claimed reduction rejected in an
unknown state.

Full detail in `docs/RELEASE_NOTES_0.6.0.md`.

---

## 9. Work order

1. **Remove `unknownStateUnsupported`** and its test. Unblocked now.
2. **Recompute or invalidate any cached Appendix 2 unknown-state figure.** They
   increase by up to four hours; anything published was short.
3. **Recompute Appendix 5 figures** for duties over 12 hours. They decrease.
4. **Update anything asserting on clause strings** — the table in §3.
5. **Check your reduction display** — `reduction_applicable` will now be null in
   cases where it was populated, correctly.
6. **After the RapidAPI re-import:** start sending the two displacement offsets,
   and switch `displacementNotIncluded` to the response-driven form in §6.

Steps 1–5 need no client changes beyond removing a guard and updating
assertions. Only step 6 waits on anything.

---

Thanks for this one. Defect 1 was a genuine safety issue and you found it by
reading the instrument against the response rather than trusting either — which
is also how the five extras surfaced. The decision to withhold the figure rather
than caveat it was right, and the note about `prior_fdp_log` in the earlier
brief has now saved a second class of the same problem.
