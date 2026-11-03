# Post-Quantum Features

Vexlore uses:
- **ML-DSA-44** (FIPS 204 / Dilithium) for signatures
- **ML-KEM-512** (FIPS 203 / Kyber) for key encapsulation
- Hybrid with Ed25519 for transition

These provide resistance against quantum computers running Shor's algorithm.

Educational implementation only.
