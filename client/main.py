import sys
import os

sys.path.append(os.getcwd())

from dataclasses import dataclass, field
import json
import socket
import time
from typing import Any
from contract import Calls as C, Answers as A, DeleteUserAnswer, GetUsersAnswer, GetUsersCall, HolePunchCall, NewRegistryAnswer, Ping, RegUserAnswer, RegUserCall
import threading
import kcp
from queue import Queue
import struct
import random

class KCPPeer(kcp.KCP):
    def __init__(self, conv_id: int, stream: 'Stream', addr, max_transmission: int = 1400, no_delay: bool = True, update_interval: int = 10, resend_count: int = 2, no_congestion_control: bool = False, send_window_size: int = 32, receive_window_size: int = 128, identity_token: Any = None) -> None:
        super().__init__(conv_id, max_transmission, no_delay, update_interval, resend_count, no_congestion_control, send_window_size, receive_window_size, identity_token)
        self.stream = stream
        self.addr = addr
        self.lock = threading.Lock()
        self.include_outbound_handler(self.output)
        
    def output(self, _, data: bytes):
        self.stream.client.send(data, self.addr)

class Stream:
    def __init__(self, conv_id: int, client: 'Client', addr: tuple, tcp_socket: socket.socket = None):
        self.conv_id = conv_id
        self.client = client
        self.addr = addr
        self.kcp = KCPPeer(conv_id, self, addr)
        self.tcp_socket = tcp_socket
        self.is_dead = False
        self.threads = []
        
        if self.tcp_socket:
            self.start_threads()

    def start_threads(self):
        t1 = threading.Thread(target=self.sender, daemon=True)
        t2 = threading.Thread(target=self.loader, daemon=True)
        self.threads.extend([t1, t2])
        t1.start()
        t2.start()

    def sender(self):
        while not self.is_dead and not self.client.got_deleted:
            try:
                output = self.tcp_socket.recv(4096)
                if not output:
                    self.close()
                    break
                with self.kcp.lock:
                    self.kcp.enqueue(output)
            except Exception as e:
                self.close()
                break
            time.sleep(0.001)

    def loader(self):
        while not self.is_dead and not self.client.got_deleted:
            try:
                with self.kcp.lock:
                    packets = list(self.kcp.get_all_received())
                for bytes_data in packets:
                    if bytes_data:
                        self.tcp_socket.sendall(bytes_data)
            except Exception as e:
                pass
            time.sleep(0.001)

    def close(self):
        if self.is_dead: return
        self.is_dead = True
        try:
            self.tcp_socket.close()
        except:
            pass
        # Send CLOSE_STREAM message to the other side via UDP
        payload = {"type": "CLOSE_STREAM", "conv_id": self.conv_id}
        self.client.send(self.client.jenc(**payload), self.addr)
        
        # Remove from client streams
        if self.conv_id in self.client.streams:
            self.client.streams.pop(self.conv_id, None)

@dataclass
class Client:
    nickname: str
    server_ip: int
    game_port: int
    
    def __post_init__(self):
        self.server_addr = (self.server_ip, 22867)
        self.addr = ("0.0.0.0", 14888)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind(self.addr)
        self.queue = Queue(32000)
        self.user_map = {}
        self.got_deleted = False
        
        self.streams: Dict[int, Stream] = {}
        
        # Test if we are host by binding to game port
        test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            test_sock.bind(("127.0.0.1", self.game_port))
            self.is_host = False
            self.game_socket = test_sock
            self.game_socket.listen()
        except OSError:
            self.is_host = True
            print("Являюсь хостом Minecraft")
            test_sock.close()
            self.game_socket = None

    def jenc(self, type: Any = None, content: Any = None, **kwargs):
        answer = {}
        if type:
            answer["type"] = type.value if hasattr(type, "value") else type
        if content:
            answer["content"] = content
        answer.update(kwargs)
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
        payload = {"type": C.REGUSR.value, "content": self.nickname}
        self.socket.sendto(self.jenc(**payload), self.server_addr)
        answer, _ = self.recv_timeout(10, "Сервер не ответил")
        answer = self.jdec(answer)
        if answer["type"] == A.REGSUC.value:
            return True
        else:
            return False
    
    def startup_punching(self):
        payload = {"type": C.GETUSR}
        self.socket.sendto(self.jenc(**payload), self.server_addr)
        answer, _ = self.recv_timeout(10, "Сервер не ответил")
        answer = self.jdec(answer)
        for nickname, addr in answer["content"].items():
            if nickname == self.nickname:
                continue
            addr = tuple(addr)
            payload = {"type": C.HLPNCH}
            self.send(self.jenc(**payload), addr, 10, 0.1)
            print(f"Подключаюсь к пользователю {nickname}")
            self.user_map[nickname] = addr

    def send(self, encoded: bytes, addr: tuple[str, int], times = 1, between: float = -1):
        for _ in range(times):
            self.socket.sendto(encoded, addr)
            if between > 0: time.sleep(between)

    def delete_user(self, answer: dict):
        nickname = answer.get('content')
        print(f"Пользователь {nickname} отключился")
        addr = self.user_map.pop(nickname, None)
        for s in list(self.streams.values()):
            if s.addr == addr:
                s.close()
        
    def new_registry(self, answer: dict):
        payload = {"type": C.HLPNCH}
        for nickname, addr in answer.get("content", {}).items():
            print(f"Пользователь {nickname} подключился!")
            addr = tuple(addr)
            self.user_map[nickname] = addr
            self.send(self.jenc(**payload), addr, 10, 0.1)
    
    def acceptor(self):
        while not self.got_deleted:
            if not self.is_host and self.game_socket:
                try:
                    conn, _ = self.game_socket.accept()
                    conv_id = random.randint(1000, 2000000000)
                    if not self.user_map:
                        conn.close()
                        continue
                    
                    target_addr = list(self.user_map.values())[0]
                    stream = Stream(conv_id, self, target_addr, conn)
                    self.streams[conv_id] = stream
                    
                    payload = {"type": "OPEN_STREAM", "conv_id": conv_id}
                    self.send(self.jenc(**payload), target_addr)
                except Exception as e:
                    pass

    def kcp_updater(self):
        while not self.got_deleted:
            for stream in list(self.streams.values()):
                try:
                    with stream.kcp.lock:
                        stream.kcp.update()
                except Exception as e:
                    pass
            time.sleep(0.01)

    def pinger(self):
        while not self.got_deleted:
            payload = {"type": C.IAMOKI, "content": self.nickname}
            self.send(self.jenc(**payload), self.server_addr)
            for nickname, addr in self.user_map.items():
                self.send(self.jenc(**payload), addr)
            time.sleep(1)

    def listener(self):
        while not self.got_deleted:
            try:
                call = self.socket.recvfrom(4096)
                answer, addr = call
                try:
                    parsed = self.jdec(answer)
                    self.queue.put((parsed, addr))
                except Exception:
                    if len(answer) >= 4:
                        conv_id = struct.unpack("<I", answer[:4])[0]
                        if conv_id in self.streams:
                            try:
                                stream = self.streams[conv_id]
                                with stream.kcp.lock:
                                    stream.kcp.receive(answer)
                            except Exception as e:
                                pass
            except OSError:
                break
    
    def executor(self):
        while not self.got_deleted:
            answer, addr = self.queue.get()

            type = answer.get("type")
            content = answer.get("content")

            if type == A.NEWUSR.value:
                self.new_registry(answer)
            elif type == A.DELUSR.value:
                if content == self.nickname:
                    self.got_deleted = True
                    self.socket.close()
                    break
                self.delete_user(answer)
            elif type == C.IAMOKI.value:
                pass
            elif type == "OPEN_STREAM" and self.is_host:
                conv_id = answer.get("conv_id")
                if conv_id not in self.streams:
                    try:
                        tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        tcp_socket.connect(("127.0.0.1", self.game_port))
                        stream = Stream(conv_id, self, addr, tcp_socket)
                        self.streams[conv_id] = stream
                    except Exception as e:
                        pass
            elif type == "CLOSE_STREAM":
                conv_id = answer.get("conv_id")
                if conv_id in self.streams:
                    self.streams[conv_id].close()

# Get IP and Port
nickname = input("Ник [любой]: ")
server_ip = input("IP сервера [брать у хоста]: ")
game_port = int(input("Порт игры: "))

while True:
    client = Client(nickname, server_ip, game_port)
    try:
        if not client.register():
            print("Ошибка регистрации")
            break
            
        client.startup_punching()

        threads = [
            threading.Thread(target=client.pinger, daemon=True),
            threading.Thread(target=client.listener, daemon=True),
            threading.Thread(target=client.executor, daemon=True),
            threading.Thread(target=client.kcp_updater, daemon=True),
        ]
        
        if not client.is_host:
            threads.append(threading.Thread(target=client.acceptor, daemon=True))
            
        for thread in threads:
            thread.start()
            
        while not client.got_deleted:
            time.sleep(1)

    except KeyboardInterrupt:
        client.got_deleted = True
        print("Отключаюсь")
        break
