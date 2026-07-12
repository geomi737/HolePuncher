from enum import Enum, auto
from typing import TypedDict

# Clients
class Calls(Enum):
    REGUSR = auto()
    GETUSR = auto()
    HLPNCH = auto()
    IAMOKI = auto()

# Sever
class Answers(Enum):
    REGSUC = auto() 
    DELUSR = auto()
    NEWUSR = auto()

# Client
class RegUserCall(TypedDict):
    type: Calls
    content: str

class GetUsersCall(TypedDict):
    type: Calls


class HolePunchCall(TypedDict):
    type: Calls

class Ping(TypedDict):
    type: Calls
    content: str

# Server
class GetUsersAnswer(TypedDict):
    content: dict[str, tuple[str, int]]

class DeleteUserAnswer(TypedDict):
    type: Answers
    content: str

class RegUserAnswer(TypedDict):
    type: Answers

class NewRegistryAnswer(TypedDict):
    type: Answers
    content: dict[str, tuple[str, int]]