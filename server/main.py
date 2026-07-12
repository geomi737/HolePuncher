from collections import deque
from dataclasses import dataclass
import queue
import sys
import os
import time
from typing import Any

sys.path.append(os.getcwd())

from contract import Calls as C, Answers as A, RegUserAnswer, RegUserCall
import json
import socket
import threading

ip = "0.0.0.0"
port = 22867
addr = (ip, port)


@dataclass
class Server:
    addr: tuple[str, int]

    def __post_init__(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind(self.addr)
        self.queue = queue.Queue(32000)
        self.user_map = {}
        self.ping_map = {}
        self.deletion_queue = deque([], 10)
        self.is_dead = False

    def jenc(self, type: Any = None, content: Any = None) -> bytes:
        answer = {}
        if type:
            answer["type"] = type.value if not isinstance(type, int) else type
        if content:
            answer["content"] = content
        return json.dumps(answer).encode()

    def jdec(self, answer: bytes):
        return json.loads(answer.decode())

    def send(self, encoded: bytes, addr: tuple[str, int], times = 1, between: float = -1):
        for _ in range(times):
            self.socket.sendto(encoded, addr)
            if between > 0: time.sleep(between)

    def listener(self):
        while not self.is_dead:
            answer, addr = self.socket.recvfrom(1024)
            answer = self.jdec(answer)
            type, content = answer.get("type"), answer.get("content")
            if type == C.REGUSR.value:
                for user, uaddr in self.user_map.items():
                    self.send(self.jenc(type=A.NEWUSR.value, content={content: addr}), uaddr)
                self.user_map[content] = addr
                payload = self.jenc(type=A.REGSUC.value)
                self.send(payload, addr)
            elif type == C.GETUSR.value:
                payload = self.jenc(content=self.user_map)
                self.send(payload, addr)
            elif type == C.IAMOKI.value:
                cur_time = time.time()
                self.ping_map[content] = cur_time


    def kicker(self):
        while not self.is_dead:
            cur_time = time.time()
            for nickname, last_time in self.ping_map.items():
                if (cur_time - last_time) >= 3:
                    for _, addr in self.user_map.items():
                        payload = self.jenc(A.DELUSR.value, nickname)
                        self.send(payload, addr)
                        self.deletion_queue.append(nickname)
            self.deleter()
            time.sleep(1)

    def deleter(self):
        for user in self.deletion_queue:
            self.ping_map.pop(user, None)
            self.user_map.pop(user, None)
        self.deletion_queue.clear()


try:
    server = Server(addr)
    threads = [
        threading.Thread(target=server.listener),
        threading.Thread(target=server.kicker)
    ]
    for thread in threads:
        thread.start()
except KeyboardInterrupt:
    server.is_dead = True