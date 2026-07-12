import sys
import os

sys.path.append(os.getcwd())

from dataclasses import dataclass
import json
import socket
import time
from typing import Any
from contract import Calls as C, Answers as A, DeleteUserAnswer, GetUsersAnswer, GetUsersCall, HolePunchCall, NewRegistryAnswer, NewRegistryCall, Ping, RegUserAnswer, RegUserCall
import threading
from queue import Queue

@dataclass
class Client:
    nickname: str
    server_ip: str
    server_port: str
    
    def __post_init__(self):
        self.server_addr = (self.server_ip, self.server_port)
        self.addr = ("0.0.0.0", 22867)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind(self.addr)
        self.queue = Queue(32000)
        self.user_map = {}
    
    def jenc(self, type: Any, content: Any):
        answer = {}
        if type:
            answer["type"] = type
        if content:
            answer["content"] = content
        return json.dumps(answer).encode()

    def jdec(self, conn: bytes):
        return json.loads(conn.decode())

    def recv_timeout(self, timeout: int, text: str):
        try:
            self.socket.settimeout(timeout)
            answer, addr = self.socket.recvfrom(1024)
            self.socket.settimeout(None)
        except TimeoutError:
            raise TimeoutError(text)
        return answer, addr

    def register(self):
        payload: RegUserCall = {"type": C.REGUSR, "content": self.nickname}
        self.socket.sendto(self.jenc(**payload), self.server_addr)
        answer, _ = self.recv_timeout(10, "Сервер не ответил")
        answer: RegUserAnswer = self.jdec(answer)
        if answer["type"] == A.REGSUC:
            return True
        else:
            return False
    
    def startup_punching(self):
        payload: GetUsersCall = {"type": C.GETUSR}
        self.socket.sendto(self.jenc(**payload), self.server_addr)
        answer, _ = self.recv_timeout(10, "Сервер не ответил")
        answer: GetUsersAnswer
        for nickname, addr in answer["content"].items():
            payload: HolePunchCall = {"type": C.HLPNCH}
            self.send(self.jenc(**payload), addr, 10, 0.1)
            self.user_map[nickname] = addr

    def send(self, encoded: bytes, addr: tuple[str, int], times = 1, between: float = -1):
        for _ in range(times):
            self.socket.sendto(encoded, addr)
            if between: time.sleep(between)
    
    # Threads methods (handled via check if/else)
    def new_registry(self, answer):
        addr: NewRegistryAnswer = answer["content"]
        payload: HolePunchCall = {"type": C.HLPNCH}
        self.send(self.jenc(**payload), addr, 10, 0.1)

    def ping(self):
        payload: Ping = {"type": C.IAMOKI}
        self.send(self.jenc(**payload), self.server_addr)

    def delete_user(self, answer: DeleteUserAnswer):
        self.user_map.pop(answer["content"])

        
# Get IP and Port
server_ip = input("IP сервера [брать у хоста]: ")
server_port = input("Порт сервера [брать у хоста]: ")


