# Phase 3 — Evaluation / back-fill

**What happens:** an hour after each forecast is logged, we want to know what *actually* happened. `fill_realized()` walks `forecasts.jsonl`, finds rows whose 1-hour horizon has elapsed but whose `realized_price_1h` field is still `null`, fetches the realized 1h candle window from Binance, and rewrites those rows in place to add `realized_price_1h`, `realized_min_1h`, `realized_max_1h`, `ape`, and `interval_score`.

**Trigger:** *currently* piggybacks on `forward()` and `main.py` — there is no independent timer. This is **gap #7** in the project memory: when validators go quiet, back-fill lags. A future independent pm2 timer would close this gap.

**Source:** [`src/eval/recorder.py`](../../src/eval/recorder.py), [`src/eval/metrics.py`](../../src/eval/metrics.py).

---

## Workflow — `fill_realized()` pass

```mermaid
flowchart TD
    Trigger[fill_realized called]
    Trigger -->|"current callers:<br/>main.py end-of-cycle<br/>forward_custom.py per request"| Read

    Read[Read forecasts.jsonl line by line<br/>each line is one forecast row]
    Read --> Loop{For each row}

    Loop -->|"realized_price_1h is not null"| Skip[Skip — already filled]
    Loop -->|"realized_price_1h is null"| AgeCheck{now ≥ prediction_ts + 1h ?}

    AgeCheck -->|"no — too early"| TooEarly[Skip — leave for next pass]
    AgeCheck -->|"yes"| Fetch[binance_client.fetch_candles<br/>for the 1h window]

    Fetch --> Compute[Compute<br/>realized_price_1h = close at prediction_ts + 1h<br/>realized_min_1h = min low across window<br/>realized_max_1h = max high across window]
    Compute --> Score[Compute via metrics.py<br/>ape = abs realized_price_1h − point ÷ realized_price_1h<br/>interval_score ≈ Precog reward.py formula]

    Score --> SchemaCheck{schema_version field present?}
    SchemaCheck -->|"v2"| WriteV2[Rewrite row preserving v2 shape<br/>features dict untouched]
    SchemaCheck -->|"absent — v1 row"| WriteV1[Rewrite row preserving v1 shape<br/>features dict not added]

    WriteV2 --> Done([Row updated in place])
    WriteV1 --> Done
    Skip --> Done
    TooEarly --> Done

    style Trigger fill:#fff3e0,stroke:#f57c00
    style Compute fill:#e8f5e9,stroke:#388e3c
    style Score fill:#e8f5e9,stroke:#388e3c
```

---

## Component view — back-fill data flow

```mermaid
graph LR
    subgraph storage["~/.precog_baseline/"]
        FJ[forecasts.jsonl]
    end

    subgraph evalmod["eval/"]
        REC[recorder.py<br/>fill_realized<br/>scans + rewrites]
        MET[metrics.py<br/>ape<br/>interval_score]
    end

    subgraph datamod["data/"]
        BC[binance_client.py<br/>fetch_candles]
    end

    subgraph external["External"]
        BAPI[Binance REST]
    end

    subgraph callers["Triggers — current"]
        MN[main.py — smoke test]
        FW[forward_custom.py — per request]
    end

    subgraph future["Triggers — gap #7 (planned)"]
        T[independent pm2 timer<br/>not yet built]
    end

    MN -.->|"calls at end of cycle"| REC
    FW -.->|"calls per validator request"| REC
    T -.->|"would call on schedule"| REC

    REC -->|"read line by line"| FJ
    REC -->|"compute scores"| MET
    REC -->|"fetch 1h window"| BC
    BC -->|"REST"| BAPI
    BAPI --> BC
    BC --> REC
    MET --> REC
    REC -->|"rewrite row in place<br/>preserves schema_version"| FJ

    classDef planned stroke-dasharray: 5 5,stroke:#999,color:#666
    class future,T planned
```

The dashed-border `future` subgraph is gap #7 — not yet implemented. When built, it removes the dependency on validator queries to drive back-fill.

---

## Schema invariants

`fill_realized()` is the **only** code path that rewrites a row in `forecasts.jsonl`. It writes exactly these fields:

| Field                | Source                              | Type       |
|----------------------|-------------------------------------|------------|
| `realized_price_1h`  | Binance close at prediction_ts + 1h | float      |
| `realized_min_1h`    | min low across 1h window            | float      |
| `realized_max_1h`    | max high across 1h window           | float      |
| `ape`                | `metrics.ape(realized, point)`      | float      |
| `interval_score`     | `metrics.interval_score(...)`       | float      |

It must **never** modify `point`, `low`, `high`, `spot`, `features`, or any timestamp field. If you find yourself wanting to do that, write a new ADR — you're proposing a schema migration, not a back-fill change.

The function tolerates **both** schema versions:

- **v2 rows** — have `schema_version: "v2"` and a `features` dict; rewritten with that shape preserved.
- **v1 rows** (pre-Phase-1, before features were captured) — lack both fields; rewritten without adding them. Don't backfill `features` retroactively — those values are lost.
