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
| **v0.5** | POST-QUANTUM EXTRA — ML-KEM node encryption, hybrid signatures, VEXQ addresses, key rotation |
| **v0.6** | STATE & DATA — clean balances, Merkle trees, prune, export/import |

## What's new in v0.6

- **Clean account-balance state** — balances live in `data/vexlore_state.json` (not bloated into every chain dump). Zero balances are dropped. `state_root` is a Merkle root over sorted `(address, balance)` pairs.
- **Merkle trees**
  - Every block has a **tx `merkle_root`** (leaves = SHA256 of each tx JSON).
  - Block hash commits to `merkle_root` + `state_root` (instead of the full tx list).
  - CLI option **23** builds / verifies a Merkle proof for any tx.
- **Prune old data** — option **24** strips full transaction lists from older blocks while keeping headers + the clean state file (configurable "keep last N").
- **Export / import** — options **25** / **26** write or load a single JSON containing chain + balances + roots (`exports/`).

## Quick Start

```bash
pip install requests cryptography
python3 vexlore_chain.py
```

You need both folders next to the script:
- `dilithium_src/`  (ML-DSA)
- `kyber_src/`      (ML-KEM)

### First run

1. Option **1** → create wallet → write down the 12 words  
2. Option **4** → faucet  
3. Option **6** → mine  
4. Option **3** → see balance  
5. Option **21** → state summary (accounts, supply, state_root)  
6. Option **23** → Merkle proof for a tx  
7. Option **24** → prune old blocks  
8. Option **25** → export chain  

## Folder layout

```
vexlore/
├── vexlore_chain.py
├── README.md
├── dilithium_src/     ← ML-DSA-44
├── kyber_src/         ← ML-KEM-512
├── wallet/            ← encrypted wallets
├── data/              ← chain + clean state + peers
│   ├── vexlore_chain.json
│   ├── vexlore_state.json   ← NEW (v0.6)
│   └── peers.json
└── exports/           ← export/import snapshots
```

## HTTP endpoints (node)

| Path | Description |
|------|-------------|
| `GET /` | Node info + state_root |
| `GET /chain` | Full chain |
| `GET /status` | Status + accounts + pruned_up_to |
| `GET /state` | Clean state summary |
| `GET /pending` | Mempool |
| `GET /peers` | Peer list |
| `GET /kem` | ML-KEM encapsulation key |
| `POST /block` | Accept block (optional ML-KEM encryption) |
| `POST /transaction` | Accept tx |
| `POST /peers` | Register peer |
| `POST /kem` | Exchange KEM keys |

Educational only — do not put real money on it.
