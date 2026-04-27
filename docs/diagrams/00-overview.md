# Overview

The system has three lifecycle phases. **Phase 1 (Deploy)** runs once per host; **Phase 2 (Runtime forecast)** runs every time a Bittensor validator queries the miner (~5 min cadence on testnet); **Phase 3 (Evaluation)** runs an hour after each forecast to back-fill the realized outcome.

For phase-level detail see:

- [Phase 1 — Deploy](./01-deploy.md)
- [Phase 2 — Runtime forecast](./02-runtime-forecast.md)
- [Phase 3 — Evaluation / back-fill](./03-evaluation.md)

---

## Workflow — system lifecycle

```mermaid
flowchart TD
    O([Operator]) -->|"./deploy.sh"| P1[Phase 1: Deploy]
    P1 -->|"baseline_miner.py installed in ~/precog-node/"| Ready[Precog node ready]
    Ready -->|"./run_miner.sh"| Running[Miner running under pm2]

    V([Bittensor validator]) -.->|"synapse query (~5 min)"| Running
    Running -->|"Phase 2: forward(synapse, cm)"| Logs[(forecasts.jsonl<br/>sentiment.jsonl<br/>futures.jsonl)]
    Running -->|"predictions + intervals"| V

    Logs -->|"1h elapsed"| P3[Phase 3: fill_realized]
    P3 -->|"rewrite row with realized + APE + interval_score"| Logs

    style P1 fill:#e3f2fd,stroke:#1976d2,stroke-width:2px
    style Running fill:#e8f5e9,stroke:#388e3c,stroke-width:2px
    style P3 fill:#fff3e0,stroke:#f57c00,stroke-width:2px
    style Logs fill:#f3e5f5,stroke:#7b1fa2,stroke-width:2px
```

---

## Component view — what lives where

```mermaid
graph TB
    subgraph external["External services"]
        BIN[Binance public REST]
        MEX[MEXC futures]
        FG[alternative.me<br/>Fear and Greed]
        CP[CryptoPanic]
        RD[Reddit]
        CM[CoinMetrics<br/>fallback only]
        BT[Bittensor validators]
    end

    subgraph host["Operator host (WSL2)"]
        subgraph hit["~/precog/hit/ — this repo"]
            SRC[src/precog_baseline_miner/]
            FW[src/miner/forward_custom.py]
            DEP[deploy.sh / run_miner.sh]
        end
        subgraph node["~/precog-node/ — cloned upstream"]
            VENV[.venv/]
            MINERS[precog/miners/baseline_miner.py<br/>copy of forward_custom.py]
            ENV[.env.miner]
        end
        subgraph storage["~/.precog_baseline/"]
            JL[forecasts.jsonl<br/>sentiment.jsonl<br/>futures.jsonl]
        end
        PM2[pm2 process]
    end

    DEP -->|"copies"| MINERS
    DEP -->|"installs into"| VENV
    PM2 -->|"runs"| MINERS
    MINERS -->|"imports"| SRC
    SRC --> JL

    BT <-.->|"axon :8092"| MINERS
    SRC <-->|"REST"| BIN
    SRC <-->|"REST"| MEX
    SRC <-->|"REST"| FG
    SRC <-->|"REST"| CP
    SRC <-->|"REST"| RD
    SRC <-.->|"fallback path only"| CM
```

---

## Key invariants an engineer should know

- **`forward_custom.py` is the deployed copy's source of truth.** `deploy.sh` copies it into `~/precog-node/precog/miners/baseline_miner.py` — never edit the copy in place.
- **All persistence is append-only JSONL.** Three log files; `fill_realized()` is the *only* function that rewrites rows in place (and only ever to fill `realized_*` / `ape` / `interval_score` fields).
- **Sentiment + futures are non-fatal.** If any sentiment or futures source fails, its signal becomes `None` and the point forecast falls back to pure momentum. The miner never crashes from a missing optional signal.
- **Asset omission ≥ asset garbage.** If both Binance and CoinMetrics fail for an asset, that asset is *omitted* from the response (validators score 0) rather than filled with a guess.
