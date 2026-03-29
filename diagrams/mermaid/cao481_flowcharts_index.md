# CAO 48.1 — Duty Validity Flowcharts: Index & Quick Reference

> **Source:** Civil Aviation Order 48.1 Instrument 2019 (Compilation No. 3, F2021C01239)
>
> **Purpose:** Decision-tree flowcharts for validating whether a proposed Flight Duty Period (FDP) is compliant under each appendix. Designed to inform the API and MCP service for automated roster checking.
>
> **⚠️ Disclaimer:** These flowcharts are derived from CAO 48.1 and are provided for reference only. They do not replace your operator's approved FMM, a qualified fatigue risk management assessment, or professional regulatory advice.

---

## Flowchart Files

| # | File | Appendix | Typical Use |
|---|------|----------|-------------|
| 1 | `cao481_appendix1_basic_limits.mermaid` | **Appendix 1** — Basic Limits | Single-pilot VFR, simple operations |
| 2 | `cao481_appendix2_multi_pilot.mermaid` | **Appendix 2** — Multi-Pilot Operations | Multi-pilot with time-zone crossings, augmented crew |
| 3 | `cao481_appendix3_multi_pilot_except_complex.mermaid` | **Appendix 3** — Multi-Pilot Except Complex | Multi-pilot, no TZ crossing, no augmented crew (e.g. **MinRes Air FIFO**) |
| 4 | `cao481_appendix4_any_operations.mermaid` | **Appendix 4** — Any Operations | Single-pilot air transport, enhanced fatigue mgmt |
| 5 | `cao481_appendix4a_balloon.mermaid` | **Appendix 4A** — Balloon Operations | Balloon ops with split-duty provisions |
| 6 | `cao481_appendix4b_medical_transport.mermaid` | **Appendix 4B** — Medical Transport & Emergency | Aeromedical, emergency service, RFDS-type ops |
| 7 | `cao481_appendix5_aerial_work.mermaid` | **Appendix 5** — Aerial Work & Associated Training | Aerial work (ag, survey, etc.) |
| 8 | `cao481_appendix5a_daylight_aerial_work.mermaid` | **Appendix 5A** — Daylight Aerial Work | Daylight-only aerial work, mustering |
| 9 | `cao481_appendix6_flight_training.mermaid` | **Appendix 6** — Flight Training | Dedicated flight training organisations |

---

## Cross-Appendix Comparison

### FDP Limits

| Appendix | FDP Table Inputs | Max FDP Range | Sectors in Table? | Split Duty Cap | Post-Split Max |
|----------|-----------------|---------------|-------------------|----------------|----------------|
| **1** | Local time only | 8–9h | No | N/A (no split duty) | N/A |
| **2** | Acclimatised time + sectors (or prior ODP + sectors for unknown) | 7.5–13h (basic), up to 18h augmented | Yes (1–3, 4, 5, 6, 7, 8+) | 16h | 6h |
| **3** | Local time + sectors | 7.5–13h | Yes (same table as App 2) | 16h | 6h |
| **4** | Local time only | 8–11h | No | 15h | 5h |
| **4A** | Split duty yes/no | 6h (no split), 10h (with split) | No | 15h | 5h |
| **4B** | Local time + op type + sectors (multi) | 10–14h | Yes (1–2, 3+) | 16h | Per table at resumption |
| **5** | Local time + op type + sectors (multi) | 10–14h | Yes (1–2, 3+) | FDP + split duration | 6h + extension |
| **5A** | Fixed (daylight only) | 14h | No | N/A | N/A |
| **6** | Local time only | 8–11h | No | 15h | 5h |

### Flight Time Limits

| Appendix | Per-FDP Limit | 28-Day | 90-Day | 365-Day |
|----------|--------------|--------|--------|---------|
| **1** | 9h (= FDP limit) | 100h | — | 1,000h |
| **2** | 10.5h (no limit if augmented) | 100h | — | 1,000h |
| **3** | 10.5h | 100h | — | 1,000h |
| **4** | Per FDP table | 100h | — | 1,000h |
| **4A** | Per FDP | 50h | — | — |
| **4B** | Per FDP table | 100h | — | 1,000h |
| **5** | Per FDP table | 170h (resets 5d off) | 450h (resets 5d off) | 1,200h (resets 28d off) |
| **5A** | Per FDP | 100h/384h, 120h/30d mustering | — | 1,200h (resets 28d off) |
| **6** | 7h | 100h | — | 1,000h |

### Cumulative Duty Time

| Appendix | 168h (7d) | 336h (14d) |
|----------|-----------|------------|
| **1** | N/A | N/A |
| **2** | 60h | 100h |
| **3** | 60h | 100h |
| **4** | 60h | 100h |
| **4A** | 45h | 84h |
| **4B** | 40h (no 36h+2LN) / 60h (with 36h+2LN) | 100h |
| **5** | N/A (uses 336h/504h recovery) | N/A |
| **5A** | N/A | N/A |
| **6** | 60h | 100h |

### Off-Duty Minimums

| Appendix | Base Min (away) | Base Min (home) | Rolling Recovery | Days Off |
|----------|----------------|-----------------|------------------|----------|
| **1** | 12h (any 24h) | 12h (any 24h) | 36h+2LN in 168h | 6 in 28d |
| **2** | 10h + displacement | 12h + displacement | 36h+2LN in 168h | 6 in 28d |
| **3** | 10h | 12h | 36h+2LN in 168h | 6 in 28d |
| **4** | 10h + displacement | 12h + displacement | 36h+2LN in 168h | 6 in 28d |
| **4A** | 10h | 10h | 2 full days in 14d | — |
| **4B** | 8h (overnight) / 10h (day) | Same | 36h+2LN in 336h or 72h+3LN in 504h | — |
| **5** | 8h (overnight) / 10h (day) | Same | 36h+2LN in 336h or 72h+3LN in 504h | — |
| **5A** | 10h | 10h | 2 consec days in 384h | — |
| **6** | 12h + 1.5× excess | 12h + 1.5× excess | 36h+2LN in 168h | 6 in 28d |

### Special Features per Appendix

| Appendix | WOCL/Early Starts | Augmented Crew | Acclimatisation | Increased FDP | Non-Flying Reduction | Late/Night Limit |
|----------|-------------------|----------------|-----------------|---------------|---------------------|-----------------|
| **1** | No | No | No | No | No | ≤3 late FDPs in 168h |
| **2** | Yes (§13) | Yes (§5) | Yes (§7) | No | No | Via WOCL |
| **3** | Yes (§11) | No | No (local time) | No | No | Via WOCL |
| **4** | Yes (§11) | No | No | No | No | Via WOCL |
| **4A** | No | No | No | No | No | No |
| **4B** | No | No | No | Yes (§1.2) | Yes (§1.5) | ≤4 late-night in 168h |
| **5** | No | No | No | Yes (§1.3) | Yes (§1.5) | ≤4 midnight–0459 in 168h |
| **5A** | No | No | No | No | No | Daylight only |
| **6** | Yes (§10) | No | No | No | No | Via WOCL |

---

## Flowchart Decision Sequence (Common Pattern)

Each appendix flowchart follows this general validation sequence, though the specifics differ:

1. **Sleep Opportunity** — Has the FCM had sufficient prior sleep?
2. **FDP Limit Lookup** — What is the base maximum FDP from the table?
3. **Split Duty Extension** — Does a mid-FDP rest period increase the limit?
4. **WOCL / Early Start Adjustments** — Do streak rules reduce the limit?
5. **FDP Duration Check** — Is the actual/proposed FDP within the adjusted limit?
6. **Extension Provisions** — If over the limit, is a valid extension available?
7. **Standby Check** — Does prior standby affect the FDP limit?
8. **Off-Duty Period** — Is the minimum off-duty before/after the FDP met?
9. **Cumulative Limits** — Are rolling-window duty and flight time limits respected?

---

## Next Steps: API Design

These flowcharts map directly to the validation logic needed in the MCP service. The existing prototype covers Appendices 1, 2, and 3. To extend coverage:

- **Appendix 4**: Requires a new FDP table (local time only, no sectors), displacement time in ODP, and the delay provisions.
- **Appendix 4A**: Simple — binary split/no-split FDP, unique sleep and recovery rules.
- **Appendix 4B**: Needs the increased FDP mechanism, non-flying duty reduction, urgent ops extension, and the late-night operations counter.
- **Appendix 5**: Similar to 4B but with different cumulative flight time tiers and the reset-after-5-days mechanism.
- **Appendix 5A**: Daylight window check, 3-night prior duty prohibition, mustering sub-rule.
- **Appendix 6**: Own FDP table, 7h flight time cap, standard WOCL/early start rules.
