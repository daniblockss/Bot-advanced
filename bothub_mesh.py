#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BotHub LAN peer discovery and deterministic task-placement prototype.

This module is intentionally NOT an execution lease/consensus system. It discovers
trusted peers and computes the same placement proposal on each node. Do not use
its result alone to start production bots across network partitions.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import platform
import secrets
import socket
import struct
import threading
import time
import uuid
from dataclasses import dataclass, asdict
from typing import Any

GROUP = os.getenv("BOTHUB_MESH_GROUP", "239.192.77.77")
PORT = int(os.getenv("BOTHUB_MESH_PORT", "47777"))
PROTOCOL = "bothub-mesh/1"
MAX_PACKET = 8192
MAX_AGE_SECONDS = 90
ANNOUNCE_SECONDS = 15


def _canonical(obj: dict[str, Any]) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sign(body: dict[str, Any], secret: bytes) -> str:
    return hmac.new(secret, _canonical(body), hashlib.sha256).hexdigest()


def _read_secret() -> bytes:
    value = os.getenv("BOTHUB_MESH_SECRET", "").strip()
    if len(value) < 32:
        raise SystemExit(
            "Defina BOTHUB_MESH_SECRET com um segredo aleatório de pelo menos 32 caracteres. "
            "Use o mesmo segredo somente nos nós autorizados; não o publique no GitHub."
        )
    return value.encode("utf-8")


@dataclass
class Peer:
    node_id: str
    hostname: str
    platform: str
    seen_at: float
    ram_free_bytes: int
    disk_free_bytes: int
    cpu_count: int
    running_bots: int
    address: str = ""

    @property
    def age_seconds(self) -> int:
        return max(0, int(time.time() - self.seen_at))

    def eligible(self, min_ram_mb: int, min_disk_gb: int, max_bots: int) -> bool:
        return (
            self.age_seconds <= MAX_AGE_SECONDS
            and self.ram_free_bytes >= min_ram_mb * 1024**2
            and self.disk_free_bytes >= min_disk_gb * 1024**3
            and self.running_bots < max_bots
        )


class BotHubMesh:
    """LAN peer membership + deterministic placement proposals; no fixed leader."""

    def __init__(self, node_id: str | None = None, min_ram_mb: int = 200,
                 min_disk_gb: int = 1, max_bots: int = 3):
        self.node_id = node_id or os.getenv("BOTHUB_NODE_ID") or str(uuid.uuid4())
        self.min_ram_mb = min_ram_mb
        self.min_disk_gb = min_disk_gb
        self.max_bots = max_bots
        self.secret = _read_secret()
        self.peers: dict[str, Peer] = {}
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.sock: socket.socket | None = None
        self.ram_free = 0
        self.disk_free = 0
        self.running_bots = 0

    def update_resources(self, ram_free_bytes: int, disk_free_bytes: int, running_bots: int) -> None:
        with self.lock:
            self.ram_free = max(0, int(ram_free_bytes))
            self.disk_free = max(0, int(disk_free_bytes))
            self.running_bots = max(0, int(running_bots))

    def _packet(self) -> bytes:
        body = {
            "protocol": PROTOCOL,
            "node_id": self.node_id,
            "hostname": socket.gethostname()[:200],
            "platform": platform.platform()[:250],
            "sent_at": int(time.time()),
            "ram_free_bytes": self.ram_free,
            "disk_free_bytes": self.disk_free,
            "cpu_count": os.cpu_count() or 1,
            "running_bots": self.running_bots,
            "nonce": secrets.token_hex(8),
        }
        envelope = {"body": body, "signature": _sign(body, self.secret)}
        return _canonical(envelope)

    def _parse(self, packet: bytes, address: str) -> Peer | None:
        if len(packet) > MAX_PACKET:
            return None
        try:
            envelope = json.loads(packet.decode("utf-8"))
            body = envelope["body"]
            signature = envelope["signature"]
            if body.get("protocol") != PROTOCOL or body.get("node_id") == self.node_id:
                return None
            expected = _sign(body, self.secret)
            if not isinstance(signature, str) or not hmac.compare_digest(signature, expected):
                return None
            sent_at = int(body["sent_at"])
            if abs(time.time() - sent_at) > MAX_AGE_SECONDS:
                return None
            node_id = str(body["node_id"])
            if not node_id or len(node_id) > 100:
                return None
            return Peer(
                node_id=node_id,
                hostname=str(body.get("hostname", ""))[:200],
                platform=str(body.get("platform", ""))[:250],
                seen_at=time.time(),
                ram_free_bytes=max(0, int(body.get("ram_free_bytes", 0))),
                disk_free_bytes=max(0, int(body.get("disk_free_bytes", 0))),
                cpu_count=max(1, min(1024, int(body.get("cpu_count", 1)))),
                running_bots=max(0, int(body.get("running_bots", 0))),
                address=address,
            )
        except (ValueError, TypeError, KeyError, UnicodeDecodeError):
            return None

    def _receiver(self) -> None:
        assert self.sock is not None
        while not self.stop_event.is_set():
            try:
                packet, addr = self.sock.recvfrom(MAX_PACKET + 1)
                peer = self._parse(packet, addr[0])
                if peer:
                    with self.lock:
                        self.peers[peer.node_id] = peer
                        self._expire_locked()
            except socket.timeout:
                continue
            except OSError:
                if not self.stop_event.is_set():
                    time.sleep(0.2)

    def _expire_locked(self) -> None:
        now = time.time()
        for node_id in list(self.peers):
            if now - self.peers[node_id].seen_at > MAX_AGE_SECONDS:
                del self.peers[node_id]

    def start(self) -> None:
        if self.sock is not None:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except (AttributeError, OSError):
            pass
        sock.bind(("", PORT))
        membership = struct.pack("=4sl", socket.inet_aton(GROUP), socket.INADDR_ANY)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, membership)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
        sock.settimeout(1.0)
        self.sock = sock
        threading.Thread(target=self._receiver, daemon=True, name="bothub-mesh-rx").start()
        threading.Thread(target=self._announce, daemon=True, name="bothub-mesh-tx").start()

    def _announce(self) -> None:
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sender.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
        try:
            while not self.stop_event.is_set():
                try:
                    sender.sendto(self._packet(), (GROUP, PORT))
                except OSError as exc:
                    print(f"[mesh] falha anunciando nó: {exc}")
                self.stop_event.wait(ANNOUNCE_SECONDS)
        finally:
            sender.close()

    def peers_snapshot(self) -> list[Peer]:
        with self.lock:
            self._expire_locked()
            own = Peer(self.node_id, socket.gethostname(), platform.platform(), time.time(),
                       self.ram_free, self.disk_free, os.cpu_count() or 1,
                       self.running_bots, "127.0.0.1")
            return [own, *sorted(self.peers.values(), key=lambda p: p.node_id)]

    def proposed_owner(self, task_id: str) -> str | None:
        """Return a stable rendezvous-hash proposal; this is not a safe execution lease."""
        candidates = [p for p in self.peers_snapshot()
                      if p.eligible(self.min_ram_mb, self.min_disk_gb, self.max_bots)]
        if not candidates:
            return None
        def score(peer: Peer) -> bytes:
            return hashlib.sha256((str(task_id) + "\0" + peer.node_id).encode()).digest()
        return max(candidates, key=score).node_id

    def status(self) -> dict[str, Any]:
        peers = self.peers_snapshot()
        return {
            "protocol": PROTOCOL,
            "node_id": self.node_id,
            "leaderless": True,
            "internet_required_for_lan_discovery": False,
            "peer_count_including_self": len(peers),
            "peers": [
                {**asdict(p), "age_seconds": p.age_seconds,
                 "eligible": p.eligible(self.min_ram_mb, self.min_disk_gb, self.max_bots)}
                for p in peers
            ],
            "warning": "Placement is a proposal only. Do not start bots from this result until a quorum-backed lease protocol is integrated.",
        }

    def close(self) -> None:
        self.stop_event.set()
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None


def main() -> int:
    parser = argparse.ArgumentParser(description="BotHub LAN peer discovery prototype")
    parser.add_argument("--node-id", default=os.getenv("BOTHUB_NODE_ID", ""))
    parser.add_argument("--min-ram-mb", type=int, default=200)
    parser.add_argument("--min-disk-gb", type=int, default=1)
    parser.add_argument("--max-bots", type=int, default=3)
    parser.add_argument("--task-id", help="Show the deterministic owner proposal for this task")
    args = parser.parse_args()
    import shutil
    mesh = BotHubMesh(args.node_id or None, args.min_ram_mb, args.min_disk_gb, args.max_bots)
    try:
        # This standalone diagnostic uses current process host storage. The production worker
        # should call update_resources() with psutil/shutil measurements before integration.
        disk = shutil.disk_usage(os.path.expanduser("~"))
        try:
            import psutil
            ram = psutil.virtual_memory().available
        except ImportError:
            ram = 0
        mesh.update_resources(ram, disk.free, 0)
        mesh.start()
        print(f"[mesh] nó {mesh.node_id}; descoberta LAN ativa em {GROUP}:{PORT}")
        while True:
            time.sleep(5)
            result = mesh.status()
            if args.task_id:
                result["proposed_owner_for_task"] = mesh.proposed_owner(args.task_id)
            print(json.dumps(result, ensure_ascii=False))
    except KeyboardInterrupt:
        return 0
    finally:
        mesh.close()


if __name__ == "__main__":
    raise SystemExit(main())
