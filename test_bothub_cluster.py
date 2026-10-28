#!/usr/bin/env python3
"""Basic deterministic checks for BotHub cluster primitives."""
import os, unittest
os.environ.setdefault("BOTHUB_CLUSTER_SECRET","unit-test-secret-not-for-production-000000")
os.environ.setdefault("BOTHUB_NODE_ID","test-node")
os.environ.setdefault("BOTHUB_ADMIN_TOKEN","unit-test-admin-token-long-enough")
import bothub_cluster as c

class ClusterTests(unittest.TestCase):
    def test_signature_stable(self):
        obj={"a":1,"b":"two"}
        self.assertEqual(c.signature(obj), c.signature({"b":"two","a":1}))
    def test_candidate_deterministic(self):
        statuses={"a":{"eligible":True},"b":{"eligible":True},"c":{"eligible":False}}
        self.assertEqual(c.candidate_for("task-1",statuses),c.candidate_for("task-1",dict(reversed(list(statuses.items())))))
        self.assertIn(c.candidate_for("task-1",statuses),("a","b"))
    def test_no_candidate(self):
        self.assertIsNone(c.candidate_for("task-1",{}))
    def test_safe_id(self):
        self.assertEqual(c.safe_id("../../hello"),"hello")
if __name__=="__main__": unittest.main(verbosity=2)
