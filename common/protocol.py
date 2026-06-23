"""
Protocolo de rede compartilhado entre servidor e cliente.

Mensagens trafegam como JSON delimitado por '\n' (uma mensagem por linha)
sobre streams asyncio. Cada mensagem é um dict com a chave "t" (type).

Manter este módulo livre de dependências de servidor/cliente para que ambos
os lados falem exatamente o mesmo "idioma".
"""
from __future__ import annotations

import json
from typing import Any

# ---- Tipos de mensagem CLIENTE -> SERVIDOR ----
C_JOIN = "join"        # {name, cls}
C_MOVE = "move"        # {dir: n|s|e|w}
C_CHAT = "chat"        # {text}
C_COMBAT = "combat"    # {action: attack|defend|skill|item|flee, item?}
C_ACTION = "action"    # {cmd: pickup|talk|rest}
C_PING = "ping"        # {}

# ---- Tipos de mensagem SERVIDOR -> CLIENTE ----
S_WELCOME = "welcome"  # {pid, you, world}
S_STATE = "state"      # {view, players, daynight, weather}
S_YOU = "you"          # {player}  -> atualiza painel lateral
S_CHAT = "chat"        # {from, text, scope}
S_LOG = "log"          # {text}    -> log de eventos/combate
S_COMBAT = "combat"    # {active, enemy, turn, options}
S_ERROR = "error"      # {text}


def encode(msg: dict[str, Any]) -> bytes:
    """Serializa uma mensagem para bytes prontos para envio (com newline)."""
    return (json.dumps(msg, separators=(",", ":")) + "\n").encode("utf-8")


def decode(line: bytes) -> dict[str, Any]:
    """Desserializa uma linha recebida em dict."""
    return json.loads(line.decode("utf-8"))
