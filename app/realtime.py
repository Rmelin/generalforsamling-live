"""WebSocket-forbindelser og udsendelse af tilstand.

WebSocket-kanalen er kun til at skubbe data ud. Alle ændringer sker via
REST-API'et, hvor rettigheder kontrolleres. Hver forbindelse har sin egen
kø og skrivetråd, så en langsom skærm ikke forsinker de andre.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import time
from typing import Any, Optional

from fastapi import WebSocket

log = logging.getLogger("live.realtime")

QUEUE_SIZE = 20

# Skærmtyper, som en forbindelse kan melde sig som.
KIND_FOH = "foh"
KIND_STAGE = "stage"
KIND_MONITOR = "monitor"
KIND_UNKNOWN = "unknown"

MAX_NAME = 40
DEVICE_STALE_AFTER = 15.0  # sekunder uden kald, før en enhed (Presto) regnes som væk
_ids = itertools.count(1)


def _clean(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    return "".join(ch for ch in text if ch.isprintable())[:limit]


class Connection:
    def __init__(self, ws: WebSocket, ip: str = "", user_agent: str = ""):
        self.ws = ws
        self.loop = asyncio.get_running_loop()
        self.queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=QUEUE_SIZE)
        self.id = next(_ids)
        self.ip = ip
        self.user_agent = _clean(user_agent, 200)
        self.kind = KIND_UNKNOWN
        self.name = ""
        self.screen = ""
        self.visible = True
        # Først når klienten har sagt "hello", ved vi, at den svarer på ping.
        # Ældre klienter (cachet JavaScript) afbrydes derfor ikke ved tavshed.
        self.greeted = False
        self.connected_at = time.time()
        self.last_seen = time.monotonic()

    def touch(self, now: Optional[float] = None) -> None:
        self.last_seen = time.monotonic() if now is None else now

    def info(self, now: float) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "ip": self.ip,
            "screen": self.screen,
            "visible": self.visible,
            "user_agent": self.user_agent,
            "connected_at": self.connected_at,
            "idle_seconds": round(max(0.0, now - self.last_seen), 1),
        }

    def offer(self, message: str) -> bool:
        try:
            self.queue.put_nowait(message)
            return True
        except asyncio.QueueFull:
            return False

    async def writer(self) -> None:
        while True:
            message = await self.queue.get()
            if message is None:
                return
            await self.ws.send_text(message)


class ConnectionManager:
    def __init__(self) -> None:
        self.connections: set[Connection] = set()
        # Enheder, der henter tilstand via HTTP (Presto): navn -> ip og sidst set
        self.devices: dict[str, dict[str, Any]] = {}

    @property
    def count(self) -> int:
        return len(self.connections)

    def add(self, conn: Connection) -> None:
        self.connections.add(conn)

    def remove(self, conn: Connection) -> None:
        self.connections.discard(conn)

    # ------------------------------------------------------------ tilstedeværelse

    def hello(self, conn: Connection, msg: dict[str, Any], allowed_kinds: set[str]) -> None:
        """Klienten fortæller, hvilken skærm den er. Rollen er tjekket mod login."""
        kind = msg.get("page")
        conn.kind = kind if kind in allowed_kinds else KIND_MONITOR
        conn.name = _clean(msg.get("name"), MAX_NAME)
        conn.screen = _clean(msg.get("screen"), 20)
        conn.visible = msg.get("visible", True) is not False
        conn.greeted = True
        conn.touch()

    def device_seen(self, name: str, ip: str) -> bool:
        """Registrér et HTTP-kald fra en enhed. Returnerer True, hvis den er ny eller var væk."""
        now = time.monotonic()
        prev = self.devices.get(name)
        was_gone = prev is None or now - prev["last_seen"] > DEVICE_STALE_AFTER
        self.devices[name] = {"ip": ip, "last_seen": now,
                              "since": time.time() if was_gone else prev["since"]}
        return was_gone

    def presence(self, now: Optional[float] = None) -> dict[str, Any]:
        now = time.monotonic() if now is None else now
        clients = sorted((c.info(now) for c in self.connections), key=lambda c: c["id"])
        devices = [
            {"name": name, "ip": d["ip"], "connected_at": d["since"],
             "idle_seconds": round(max(0.0, now - d["last_seen"]), 1),
             "online": now - d["last_seen"] <= DEVICE_STALE_AFTER}
            for name, d in sorted(self.devices.items())
        ]
        return {
            "type": "presence",
            "server_time": time.time(),
            "clients": clients,
            "devices": devices,
            "stages": sum(1 for c in clients if c["kind"] == KIND_STAGE),
        }

    def sweep(self, stale_after: float, now: Optional[float] = None) -> list[Connection]:
        """Afbryd klienter, der har sagt hello, men ikke har svaret i stale_after sekunder.

        En skærm, der mister netværket uden at lukke forbindelsen (f.eks. en Pi uden
        WiFi), opdages så inden for et halvt minut i stedet for efter flere minutter.
        """
        now = time.monotonic() if now is None else now
        dropped = [c for c in self.connections if c.greeted and now - c.last_seen > stale_after]
        for conn in dropped:
            log.info("Ingen svar fra %s (%s) – afbrydes", conn.kind, conn.ip)
            self._drop(conn)
        return dropped

    def send_presence(self) -> None:
        """Send oversigten over tilsluttede skærme – kun til FOH."""
        self.broadcast_text(json.dumps(self.presence(), ensure_ascii=False), only_kind=KIND_FOH)

    # ------------------------------------------------------------ udsendelse

    def broadcast_text(self, message: str, only_kind: Optional[str] = None) -> None:
        try:
            current = asyncio.get_running_loop()
        except RuntimeError:
            current = None
        for conn in list(self.connections):
            if only_kind is not None and conn.kind != only_kind:
                continue
            if conn.loop is current:
                self._deliver(conn, message)
            else:
                # Forbindelsen tilhører en anden event loop (f.eks. i tests).
                conn.loop.call_soon_threadsafe(self._deliver, conn, message)

    def _deliver(self, conn: Connection, message: str) -> None:
        if conn not in self.connections:
            return
        if not conn.offer(message):
            # Klienten hænger: luk den. Den genforbinder og får et frisk snapshot.
            log.warning("WebSocket-klient for langsom – afbrydes")
            self._drop(conn)

    def _drop(self, conn: Connection) -> None:
        """Fjern forbindelsen og få dens skrivetråd til at stoppe."""
        self.remove(conn)

        def stop() -> None:
            try:
                conn.queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            conn.queue.put_nowait(None)

        try:
            current = asyncio.get_running_loop()
        except RuntimeError:
            current = None
        if conn.loop is current:
            stop()
        else:
            conn.loop.call_soon_threadsafe(stop)

    def broadcast(self, payload: dict[str, Any]) -> None:
        self.broadcast_text(json.dumps(payload, ensure_ascii=False))
