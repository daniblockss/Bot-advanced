#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for the experimental BotHub mesh protocol (no network required)."""
import os
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("BOTHUB_MESH_SECRET", "test-only-secret-do-not-use-in-production-0000000000")

import bothub_mesh


class MeshTests(unittest.TestCase):
    def setUp(self):
        self.mesh = bothub_mesh.BotHubMesh(
            node_id="node-self", min_ram_mb=100, min_disk_gb=1, max_bots=3
        )
        self.mesh.update_resources(1024**3, 10 * 1024**3, 0)

    def tearDown(self):
        self.mesh.close()

    def test_signed_packet_round_trip(self):
        packet = self.mesh._packet()
        peer = bothub_mesh.BotHubMesh(node_id="node-other")
        try:
            parsed = peer._parse(packet, "192.168.1.20")
            self.assertIsNotNone(parsed)
            self.assertEqual(parsed.node_id, "node-self")
        finally:
            peer.close()

    def test_tampered_packet_is_rejected(self):
        import json
        envelope = json.loads(self.mesh._packet().decode("utf-8"))
        envelope["body"]["ram_free_bytes"] = 999999999999
        packet = bothub_mesh._canonical(envelope)
        peer = bothub_mesh.BotHubMesh(node_id="node-other")
        try:
            self.assertIsNone(peer._parse(packet, "192.168.1.20"))
        finally:
            peer.close()

    def test_self_packet_is_ignored(self):
        self.assertIsNone(self.mesh._parse(self.mesh._packet(), "127.0.0.1"))

    def test_owner_proposal_is_deterministic(self):
        now = time.time()
        peers = [
            bothub_mesh.Peer("node-a", "a", "Linux", now, 2 * 1024**3, 5 * 1024**3, 4, 0),
            bothub_mesh.Peer("node-b", "b", "Linux", now, 2 * 1024**3, 5 * 1024**3, 4, 0),
            bothub_mesh.Peer("node-c", "c", "Linux", now, 2 * 1024**3, 5 * 1024**3, 4, 0),
        ]
        with patch.object(self.mesh, "peers_snapshot", return_value=peers):
            first = self.mesh.proposed_owner("bot-123")
        with patch.object(self.mesh, "peers_snapshot", return_value=list(reversed(peers))):
            second = self.mesh.proposed_owner("bot-123")
        self.assertEqual(first, second)
        self.assertIn(first, {"node-a", "node-b", "node-c"})

    def test_no_eligible_peer_returns_none(self):
        with patch.object(self.mesh, "peers_snapshot", return_value=[]):
            self.assertIsNone(self.mesh.proposed_owner("bot-123"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
