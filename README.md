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

## What’s new in v0.5

- **ML-KEM-512** for encrypted peer-to-peer messages (block/tx gossip)
- **Hybrid signatures** — every transaction is signed with both Ed25519 *and* ML-DSA-44
- **Quantum-safe addresses** start with `VEXQ...` (hash of both public keys)
- **Key rotation** — rotate keys for any address while keeping the old one usable for receiving

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
5. Option **12** → try key rotation  
6. Option **16** → add a peer (KEM keys are exchanged automatically)

## Folder layout

```
vexlore/
├── vexlore_chain.py
├── demo.py
├── README.md
├── dilithium_src/     ← ML-DSA-44
├── kyber_src/         ← ML-KEM-512
├── wallet/            ← encrypted wallets
└── data/              ← chain + peers
```

Educational only — do not put real money on it.
