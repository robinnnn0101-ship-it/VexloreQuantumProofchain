# Vexlore Quantumproof Chain

**Free educational post-quantum blockchain** named **Vexlore**.

Uses **ML-DSA-44** (FIPS 204) signatures (or demo FakePQ if `dilithium_src` is missing).

> Not production-ready. Clean, runnable prototype for learning.

## Version History

| Version | Focus |
|---------|--------|
| **v0.1–v0.7** | Core → network → wallet → PQ extras → state → API |
| **v0.8** | CONSENSUS — multi-miners, orphans, reorg, block reward |
| **v0.9** | CONTRACTS (light) — multi-sig, time-locks, send rules |
| **v1.0** | NETWORK + PEERS — multi-node gossip, node identity, difficulty adjust |

## What's new in v1.0

- **Peer discovery & gossip** — HTTP-based, `/announce`, `/block`, `/tx`, `/peers`
- **Block & tx propagation** — mined blocks and new transactions are pushed to connected peers
- **Node identity** — each node has a PQ keypair + short node ID (`N` + 10 hex)
- **Difficulty adjustment** — every 20 blocks, retarget toward ~20 s block time
- **peers.json** — persistent peer list
- **Explorer upgrades** — live peer table, node ID, difficulty column
- **CLI** — connect peer (21), list peers (22), broadcast mempool (23), force sync (24)
- **Bootstrap** — `python3 vexlore_chain.py --peer http://other:5000`

## Quick Start

```bash
pip install requests cryptography
# optional for real PQ: keep dilithium_src/ next to the script
python3 vexlore_chain.py
```

### Multi-node testnet (2 terminals)

```bash
# Terminal A (default port 5000)
python3 vexlore_chain.py

# Terminal B (different port + bootstrap)
python3 vexlore_chain.py --port 5001 --peer http://127.0.0.1:5000
```

Then on either node:
1. Create wallet → Faucet → Mine a few blocks
2. Watch the other node catch up automatically (or use **24** Force sync)
3. Create multi-sig / time-lock → they appear on both explorers

### Try contracts (same as v0.9)

1. Create wallet (1) → Faucet (4) → Mine (6)
2. **14** — create multi-sig
3. **15** — sign until threshold → funds release
4. **16** — time-lock for 30 seconds
5. **17** — claim when ready
6. **18** — list contracts
7. **19** — show send rules

## Menu map

| # | Action |
|---|--------|
| 1–13 | Wallet, send, mine, orphans, multi-miner |
| **14** | Create multi-sig vault |
| **15** | Sign multi-sig release |
| **16** | Create time-lock |
| **17** | Claim time-lock |
| **18** | List contracts |
| **19** | Show send rules |
| **20** | Open explorer URL |
| **21** | Connect to peer |
| **22** | List peers |
| **23** | Broadcast mempool |
| **24** | Force sync from peers |
| 0 | Exit |

## HTTP endpoints

| Path | Description |
|------|-------------|
| `/` | Node summary |
| `/status` | Height, tip, node_id, difficulty, peers |
| `/explorer` | Pretty UI |
| `/chain` | Full chain |
| `/block/N` | Single block by height |
| `/mempool` | Pending txs |
| `/contracts` | All contracts |
| `/peers` | Known peers |
| `POST /announce` | Peer handshake |
| `POST /block` | Receive block |
| `POST /tx` | Receive transaction |

Educational only — do not put real money on it.
