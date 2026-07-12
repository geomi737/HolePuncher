import sys
import os

sys.path.append(os.getcwd())

import json
import socket

users_hash_map = {}
server_ip = "localhost"
server_port = 22867
addr = (server_ip, server_port)


mirror = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
mirror.bind(addr)
print("Порт 22867 успешно зарезервирован")

while True:
    conn, addr = mirror.recvfrom(1024)
    ip, port = addr
    data = json.loads(conn.decode())
    users_hash_map[ip] = port
    mirror.sendto(json.dumps({"self": ip, "other": users_hash_map}).encode(), addr)