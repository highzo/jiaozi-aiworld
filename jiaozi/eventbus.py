"""进程内事件总线：把后端发生的一切（终端输出、AI 步骤、文件变化）推给所有前端。

单机场景不需要 Redis。每个 SSE 客户端一个有限队列，慢客户端丢旧事件而不是阻塞内核。
"""
from __future__ import annotations

import json
import queue
import threading
import time
from typing import Any


class Subscriber:
    __slots__ = ("q", "cid", "closed")

    def __init__(self, cid: str, maxsize: int = 2000):
        self.cid = cid
        self.q: queue.Queue = queue.Queue(maxsize=maxsize)
        self.closed = False

    def push(self, item: dict) -> None:
        if self.closed:
            return
        try:
            self.q.put_nowait(item)
        except queue.Full:
            # 丢掉最旧的一条，保证实时性
            try:
                self.q.get_nowait()
            except queue.Empty:
                pass
            try:
                self.q.put_nowait(item)
            except queue.Full:
                pass

    def close(self) -> None:
        self.closed = True
        try:
            self.q.put_nowait({"__close__": True})
        except queue.Full:
            pass


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, Subscriber] = {}
        self._lock = threading.RLock()
        self._seq = 0

    # ---- 订阅 ----
    def subscribe(self, cid: str) -> Subscriber:
        sub = Subscriber(cid)
        with self._lock:
            self._subs[cid] = sub
        return sub

    def unsubscribe(self, cid: str) -> None:
        with self._lock:
            sub = self._subs.pop(cid, None)
        if sub:
            sub.close()

    def count(self) -> int:
        with self._lock:
            return len(self._subs)

    # ---- 发布 ----
    def publish(self, etype: str, data: Any = None, **extra) -> dict:
        with self._lock:
            self._seq += 1
            ev = {"t": etype, "seq": self._seq, "ts": time.time(),
                  "d": data}
            if extra:
                ev.update(extra)
            subs = list(self._subs.values())
        for s in subs:
            s.push(ev)
        return ev

    # ---- 便捷发布 ----
    def term(self, sid: str, text: str) -> None:
        self.publish("term", text, id=sid)

    def notify(self, title: str, body: str = "", level: str = "info") -> None:
        self.publish("notify", {"title": title, "body": body, "level": level})

    def toast(self, text: str, level: str = "info") -> None:
        self.publish("toast", {"text": text, "level": level})


BUS = EventBus()


def sse_format(ev: dict) -> bytes:
    payload = json.dumps(ev, ensure_ascii=False, default=str)
    return f"data: {payload}\n\n".encode("utf-8")
