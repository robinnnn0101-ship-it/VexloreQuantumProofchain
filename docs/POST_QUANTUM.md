# Post-Quantum Features

Vexlore uses hybrid cryptography for educational quantum resistance:

## Algorithms

- **ML-DSA-44** (FIPS 204 / Dilithium) — digital signatures
- **ML-KEM-512** (FIPS 203 / Kyber) — key encapsulation mechanism
- **Ed25519** — classical signatures (hybrid mode)

## Why hybrid?

During the transition period, hybrid schemes provide security even if one primitive is broken.

## Quantum threat

Shor's algorithm breaks ECDSA / Ed25519 / RSA.  
Grover weakens symmetric crypto (use longer keys).

This chain demonstrates practical PQ integration in a simple blockchain.

Educational only.
