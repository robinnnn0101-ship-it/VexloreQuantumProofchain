# Vexlore Quantumproof Chain

**Free educational post-quantum blockchain** named **Vexlore**.

Uses real **ML-DSA-44** (FIPS 204) + **ML-KEM-512** (FIPS 203) + hybrid Ed25519 signatures.

> Not production-ready. Clean, runnable prototype for learning.

## Version History

| Version | Focus |
|---------|--------|
| **v0.1** | Core chain, wallets, PoW, ML-DSA |
| **v0.2** | NETWORK — multi-node, gossip, auto-sync |
| **v0.3** | BETTER CHAIN — adaptive difficulty, bigger blocks, atomic saves |
| **v0.4** | WALLET UPGRADES — seed phrase, encrypted wallets, multi-address, history |
| **v0.5** | POST-QUANTUM EXTRA — ML-KEM, hybrid sigs, VEXQ, key rotation |
| **v0.6** | STATE & DATA — clean balances, Merkle trees, prune, export/import |
| **v0.7** | API & TOOLS — JSON-RPC, block explorer, log viewer, better CLI |

## What's new in v0.7

- **Simple JSON-RPC** — `POST /rpc` (and `GET /rpc?method=...`)
  - Methods: `getinfo`, `getblockcount`, `getblock`, `getbalance`, `listbalances`,
    `getmempool`, `gettransaction`, `getstate`, `validate`, `getpeers`, `help`
- **Block explorer** — local web UI at `/explorer` (dark theme, recent blocks, balances, mempool)
- **Log viewer** — ring buffer + `data/vexlore.log`; CLI option **27** and `GET /logs`
- **Improved CLI** — aliases (`mine`, `bal`, `logs`, `explorer`, …) + grouped menu

## Quick Start

```bash
pip install requests cryptography
python3 vexlore_chain.py
```

Open the explorer in a browser:

```
http://127.0.0.1:5000/explorer
```

### RPC examples

```bash
# info
curl -s -X POST http://127.0.0.1:5000/rpc \
  -H 'Content-Type: application/json' \
  -d '{"method":"getinfo","id":1}'

# balance
curl -s 'http://127.0.0.1:5000/rpc?method=getbalance&address=VEXQ...'

# block by height
curl -s 'http://127.0.0.1:5000/block/0'

# logs
curl -s 'http://127.0.0.1:5000/logs?n=20'
```

### CLI aliases

| Alias | Action |
|-------|--------|
| `mine` / `m` | Mine block |
| `bal` / `balance` | Show balance |
| `send` / `tx` | Send transaction |
| `logs` | View recent logs |
| `explorer` / `ui` | Open block explorer |
| `rpc` | Print RPC help |
| `state` | State summary |
| `help` / `?` | Help |

## Folder layout

```
vexlore/
├── vexlore_chain.py
├── README.md
├── dilithium_src/
├── kyber_src/
├── wallet/
├── data/
│   ├── vexlore_chain.json
│   ├── vexlore_state.json
│   ├── peers.json
│   └── vexlore.log          ← NEW (v0.7)
└── exports/
```

Educational only — do not put real money on it.
