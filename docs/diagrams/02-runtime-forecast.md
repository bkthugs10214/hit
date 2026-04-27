# Phase 2 — Runtime forecast

**What happens:** for every validator query (Bittensor wraps it as a `synapse` object), the Precog `Miner` class dynamically imports our `baseline_miner.py` and calls `forward(synapse, cm)`. We loop over the assets in the request, fetch candles + sentiment + futures, compute the point forecast and interval, log everything to JSONL, and return the populated synapse. A two-tier fallback chain (Binance → CoinMetrics → omit) guarantees we never return garbage.

**Trigger:** Bittensor validator request, ~5 min cadence on testnet.

**Source:** [`src/miner/forward_custom.py`](../../src/miner/forward_custom.py).

This is the most important diagram in the repo — most engineering work touches the runtime path.

---

## Workflow — single validator request, per asset

```mermaid
sequenceDiagram
    autonumber
    participant V as Validator
    participant PM as Precog Miner<br/>(upstream)
    participant FW as forward_custom.py
    participant BC as binance_client
    participant SA as sentiment aggregator
    participant FA as futures aggregator
    participant FE as features.*
    participant FC as forecast.*
    participant LG as eval/recorders
    participant FS as ~/.precog_baseline/<br/>*.jsonl

    V->>PM: synapse(assets, timestamp)
    PM->>FW: await forward(synapse, cm)

    loop for each asset in synapse.assets
        rect rgba(200, 230, 255, 0.4)
        Note over FW,FS: Primary path — Binance
        FW->>BC: fetch_candles(asset, limit=100)
        BC-->>FW: 100 × 1-min OHLCV DataFrame
        FW->>SA: fetch_all_sentiment(asset)
        SA-->>FW: SentimentBundle (F&G + CryptoPanic + Reddit)
        FW->>FE: sentiment_signal(bundle)
        FE-->>FW: float in [-1, 1] or None
        FW->>LG: log_sentiment(asset, bundle, sig)
        LG->>FS: append sentiment.jsonl
        FW->>FA: fetch_all_futures(asset)
        FA-->>FW: FuturesBundle (MEXC funding + OI)
        FW->>FE: futures_signal(bundle)
        FE-->>FW: float in [-1, 1] or None
        FW->>LG: log_futures(asset, bundle, sig)
        LG->>FS: append futures.jsonl
        FW->>FC: compute_point_forecast(candles, sent, fut, weights, shrinkage)
        FC-->>FW: PointForecast(point, features)
        FW->>FC: compute_interval(candles, point, multiplier)
        FC-->>FW: Interval(low, high, features)
        FW->>LG: log_forecast(asset, ts, spot, point, low, high, features)
        LG->>FS: append forecasts.jsonl
        end
    end

    alt all assets succeeded on Binance
        FW-->>PM: synapse with predictions + intervals
    else any asset failed Binance
        rect rgba(255, 230, 200, 0.4)
        Note over FW: Fallback path — CoinMetrics
        FW->>FW: cm_fallback(asset, cm)
        Note right of FW: spot ± 2% margin<br/>no sentiment / futures / candles
        FW-->>PM: synapse (cm-fallback values)
        end
    else both failed for an asset
        Note right of FW: omit asset entirely<br/>better than guessing
        FW-->>PM: synapse (asset omitted from dicts)
    end

    PM-->>V: synapse response
```

The shaded sections separate the **primary** (full-feature) and **fallback** (degraded but valid) code paths. Both record some artifact — the primary writes three JSONL rows per asset, the fallback writes none. This is deliberate: fallback rows would pollute the data we use to evaluate signal quality.

---

## Component view — modules used during a forward call

```mermaid
graph TB
    subgraph apis["External APIs"]
        BAPI[Binance REST<br/>api.binance.us]
        MEXAPI[MEXC futures]
        FGAPI[alternative.me]
        CPAPI[CryptoPanic API<br/>requires API key]
        RDAPI[Reddit JSON]
        CMAPI[CoinMetrics cm client]
    end

    subgraph data["data/ — fetchers"]
        BC[binance_client.py<br/>fetch_candles]
        CDL[candles.py<br/>DataFrame helpers]
        FG[sentiment/fear_greed.py<br/>TTL-cached]
        CP[sentiment/cryptopanic.py]
        RD[sentiment/reddit.py]
        SAGG[sentiment/__init__.py<br/>fetch_all_sentiment]
        MEX[futures/mexc_futures.py]
        FAGG[futures/__init__.py<br/>fetch_all_futures]
    end

    subgraph features["features/"]
        RET[returns.py<br/>5m and 15m momentum]
        VOL[volatility.py<br/>realized → hourly vol]
        SSIG[sentiment.py<br/>SentimentBundle → float]
        FSIG[futures.py<br/>FuturesBundle → float]
    end

    subgraph forecast["forecast/"]
        BASE[baseline.py<br/>compute_point_forecast<br/>= momentum × 1−shrinkage<br/>+ sent × W_s + fut × W_f]
        ITVL[interval.py<br/>compute_interval<br/>= hourly_vol clamped]
    end

    subgraph evalrec["eval/ — recorders"]
        REC[recorder.py<br/>log_forecast]
        SREC[sentiment_recorder.py]
        FREC[futures_recorder.py]
    end

    subgraph miner["miner/"]
        FW[forward_custom.py<br/>async forward]
        AD[adapter.py<br/>asset → symbol<br/>+ cm_fallback]
    end

    subgraph storage["~/.precog_baseline/"]
        FJ[forecasts.jsonl]
        SJ[sentiment.jsonl]
        FUJ[futures.jsonl]
    end

    BAPI --> BC
    BC --> CDL
    FGAPI --> FG
    CPAPI --> CP
    RDAPI --> RD
    FG --> SAGG
    CP --> SAGG
    RD --> SAGG
    MEXAPI --> MEX
    MEX --> FAGG

    FW -->|"candles"| BC
    FW -->|"asset → symbol"| AD
    AD -.->|"on Binance failure"| CMAPI
    FW -->|"bundle"| SAGG
    FW -->|"bundle"| FAGG

    SAGG --> SSIG
    FAGG --> FSIG
    BC --> RET
    BC --> VOL

    SSIG --> BASE
    FSIG --> BASE
    RET --> BASE
    VOL --> ITVL
    BASE --> ITVL

    BASE --> FW
    ITVL --> FW

    FW --> REC
    FW --> SREC
    FW --> FREC

    REC --> FJ
    SREC --> SJ
    FREC --> FUJ
```

---

## Forecast formula at a glance

```
point = spot × (1 + base_return × (1 − POINT_SHRINKAGE)
                  + sentiment_sig × SENTIMENT_WEIGHT      (if sentiment available)
                  + futures_sig   × FUTURES_WEIGHT)       (if futures available)

base_return = blend(ret_5m, ret_15m)             (in features/returns.py)

interval = [point − vol_halfwidth, point + vol_halfwidth]
vol_halfwidth = hourly_vol × INTERVAL_MULTIPLIER
              clamped to [0.1%, 7.5%] of point
```

`POINT_SHRINKAGE`, `SENTIMENT_WEIGHT`, `FUTURES_WEIGHT`, and `INTERVAL_MULTIPLIER` are all read from env via [`config.py`](../../src/config.py).

---

## Failure semantics

| Failure                       | Effect                                                                    |
|-------------------------------|---------------------------------------------------------------------------|
| Sentiment source fails        | That source's contribution drops to 0; bundle re-normalizes proportionally |
| All sentiment sources fail    | `sentiment_sig = None` → falls out of the point formula                    |
| Futures fetch fails           | `futures_sig = None` → falls out of the point formula                      |
| Binance fails for one asset   | Fall through to CoinMetrics fallback (point = spot, interval = spot ± 2%) |
| CoinMetrics also fails        | Asset is **omitted** from response (better than garbage)                   |
| Forecast/interval throws      | Caught at the outer try; treated as Binance failure → CM fallback          |

The single rule: **never return a number we don't believe in**. Validators score missing assets at zero reward, but they score *bad* numbers more harshly through APE — so omission dominates fabrication.
