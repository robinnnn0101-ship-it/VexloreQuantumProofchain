import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ml_dsa = types.ModuleType("dilithium_py.ml_dsa")
ml_dsa.ML_DSA_44 = object()
package = types.ModuleType("dilithium_py")
package.__path__ = []

with patch.dict(sys.modules, {
    "dilithium_py": package,
    "dilithium_py.ml_dsa": ml_dsa,
}), patch.object(Path, "mkdir"):
    import vexlore_chain as chain_module


class SecurityTests(unittest.TestCase):
    def make_chain(self):
        chain = object.__new__(chain_module.VexloreChain)
        genesis = chain_module.canonical_genesis_block()
        chain.chain = [genesis]
        chain.pending = []
        chain.balances = {}
        chain.current_difficulty = chain_module.INITIAL_DIFFICULTY
        chain._save = lambda: None
        return chain

    def make_reward_block(self, chain, amount=chain_module.BLOCK_REWARD, difficulty=None):
        block = chain_module.Block(
            index=len(chain.chain),
            timestamp=chain_module.GENESIS_TIMESTAMP + 1.0,
            transactions=[
                chain_module.Transaction(
                    tx_id="reward-1",
                    sender="VEXLORE_NETWORK",
                    recipient="miner",
                    amount=amount,
                    timestamp=chain_module.GENESIS_TIMESTAMP + 1.0,
                    public_key="",
                    signature="",
                    memo="Block reward",
                )
            ],
            previous_hash=chain.last_block.hash,
            difficulty=chain_module.INITIAL_DIFFICULTY if difficulty is None else difficulty,
            miner="miner",
        )
        block.mine()
        return block

    def test_transaction_key_must_derive_claimed_sender(self):
        tx = chain_module.Transaction(
            tx_id="tx",
            sender=chain_module.address_from_pubkey(b"victim-key"),
            recipient="recipient",
            amount=1.0,
            timestamp=1.0,
            public_key=b"attacker-key".hex(),
            signature="00",
        )
        with patch.object(chain_module, "pq_verify", return_value=True):
            self.assertFalse(tx.verify())
            tx.sender = chain_module.address_from_pubkey(bytes.fromhex(tx.public_key))
            self.assertTrue(tx.verify())

    def test_sender_spoof_cannot_enter_mempool(self):
        chain = self.make_chain()
        chain.balances["victim"] = 20.0
        tx = chain_module.Transaction(
            tx_id="forged",
            sender="victim",
            recipient="attacker",
            amount=5.0,
            timestamp=chain_module.GENESIS_TIMESTAMP + 1.0,
            public_key=b"attacker-key".hex(),
            signature="00",
        )
        with patch.object(chain_module, "pq_verify", return_value=True):
            self.assertFalse(chain.add_transaction(tx))
        self.assertEqual(chain.pending, [])

    def test_network_issuance_is_not_accepted_as_a_user_transaction(self):
        chain = self.make_chain()
        tx = chain_module.Transaction(
            tx_id="fake-faucet",
            sender="VEXLORE_NETWORK",
            recipient="attacker",
            amount=1_000_000.0,
            timestamp=101.0,
            public_key="",
            signature="",
            memo="Faucet drop",
        )
        self.assertFalse(chain.add_transaction(tx))

    def test_peer_cannot_mint_arbitrary_reward(self):
        chain = self.make_chain()
        block = self.make_reward_block(chain, amount=1_000_000.0)
        self.assertFalse(chain.add_block_from_peer(block))
        self.assertEqual(chain.get_balance("miner"), 0.0)

    def test_peer_cannot_set_zero_difficulty(self):
        chain = self.make_chain()
        block = self.make_reward_block(chain, difficulty=0)
        self.assertFalse(chain.add_block_from_peer(block))

    def test_alternate_genesis_is_not_accepted(self):
        local_chain = self.make_chain()
        alternate = chain_module.Block(
            index=0,
            timestamp=1.0,
            transactions=[],
            previous_hash="0" * 64,
            difficulty=chain_module.INITIAL_DIFFICULTY,
            miner="genesis",
        )
        alternate.hash = alternate.compute_hash()
        remote_chain = self.make_chain()
        remote_chain.chain = [alternate]
        remote_chain.chain.append(self.make_reward_block(remote_chain))
        self.assertFalse(local_chain.replace_chain(remote_chain.chain))
        self.assertEqual(local_chain.chain[0].hash, chain_module.canonical_genesis_block().hash)

    def test_sync_does_not_auto_add_advertised_peers(self):
        server = object.__new__(chain_module.NodeServer)
        server.chain = self.make_chain()
        server.self_url = "http://127.0.0.1:5000"
        server.peers = chain_module.PeerManager.__new__(chain_module.PeerManager)
        server.peers.peers = {"http://8.8.8.8:5000"}
        with patch.object(server.peers, "fetch_chain", return_value=None), patch.object(
            server.peers, "fetch_peers", return_value=["http://1.1.1.1:80"]
        ) as fetch_peers, patch.object(server.peers, "add") as add_peer, patch.object(
            server.peers, "request"
        ):
            server.sync_with_peers()
        add_peer.assert_not_called()
        fetch_peers.assert_not_called()

    def test_valid_reward_is_accepted_and_chain_validates(self):
        chain = self.make_chain()
        block = self.make_reward_block(chain)
        self.assertTrue(chain.add_block_from_peer(block))
        self.assertEqual(chain.get_balance("miner"), chain_module.BLOCK_REWARD)
        self.assertTrue(chain.is_valid())

    def test_miner_can_claim_fixed_reward_without_faucet(self):
        chain = self.make_chain()
        block = chain.mine_pending("miner")
        self.assertEqual(len(block.transactions), 1)
        self.assertEqual(block.transactions[0].amount, chain_module.BLOCK_REWARD)
        self.assertTrue(chain.is_valid())

    def test_private_peer_url_is_rejected_before_request(self):
        manager = chain_module.PeerManager()
        with patch.object(chain_module.requests, "request") as request:
            with self.assertRaises(ValueError):
                manager.request("get", "http://127.0.0.1:8080", "/chain", timeout=1)
            request.assert_not_called()

    def test_peer_hostnames_and_non_public_ip_addresses_are_rejected(self):
        manager = chain_module.PeerManager()
        with patch.object(chain_module.socket, "getaddrinfo") as resolve:
            self.assertIsNone(manager._normalize_url("http://peer.example:5000"))
            self.assertIsNone(manager._normalize_url("http://10.0.0.1:5000"))
            resolve.assert_not_called()

    def test_public_peer_request_does_not_follow_redirects(self):
        manager = chain_module.PeerManager()
        response = object()
        with patch.object(chain_module.requests, "request", return_value=response) as request:
            self.assertIs(manager.request("get", "http://8.8.8.8:5000", "/chain"), response)
        self.assertFalse(request.call_args.kwargs["allow_redirects"])

    def test_node_binds_to_loopback_by_default(self):
        chain = self.make_chain()
        with patch.object(chain_module.PeerManager, "__init__", return_value=None), patch.object(
            chain_module.NodeServer, "_guess_local_ip"
        ) as guess:
            node = chain_module.NodeServer(chain, port=5000)
        self.assertEqual(node.host, "127.0.0.1")
        self.assertEqual(node.self_url, "http://127.0.0.1:5000")
        guess.assert_not_called()

    def test_persisted_balances_are_rebuilt_from_validated_chain(self):
        chain = self.make_chain()
        stored = {
            "chain": [block.to_dict() for block in chain.chain],
            "balances": {"attacker": 1_000_000.0},
            "difficulty": 0,
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            data_dir.mkdir()
            chain_file = data_dir / "chain.json"
            chain_file.write_text(json.dumps(stored))
            with patch.object(chain_module, "CHAIN_FILE", chain_file):
                loaded = chain_module.VexloreChain()
        self.assertEqual(loaded.balances, {})
        self.assertEqual(loaded.current_difficulty, chain_module.INITIAL_DIFFICULTY)

    def test_invalid_saved_chain_is_archived_before_reset(self):
        remote_chain = self.make_chain()
        alternate_genesis = chain_module.Block(
            index=0,
            timestamp=1.0,
            transactions=[],
            previous_hash="0" * 64,
            difficulty=chain_module.INITIAL_DIFFICULTY,
            miner="genesis",
        )
        alternate_genesis.hash = alternate_genesis.compute_hash()
        remote_chain.chain = [alternate_genesis]
        invalid = self.make_reward_block(remote_chain, amount=1_000_000.0)
        stored = {"chain": [alternate_genesis.to_dict(), invalid.to_dict()]}
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            data_dir.mkdir()
            chain_file = data_dir / "chain.json"
            chain_file.write_text(json.dumps(stored))
            with patch.object(chain_module, "CHAIN_FILE", chain_file), patch.object(
                chain_module, "DATA_DIR", data_dir
            ):
                loaded = chain_module.VexloreChain()
            backups = list(data_dir.glob("chain.json.invalid-*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(len(loaded.chain), 1)


if __name__ == "__main__":
    unittest.main()
