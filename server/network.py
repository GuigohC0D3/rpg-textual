"""
Camada de transporte do servidor (baixo nível).

Responsável apenas por aceitar conexões TCP, enquadrar mensagens JSON
delimitadas por '\n' e repassar eventos (connect/message/disconnect) para a
lógica de jogo via callbacks. Não conhece regras do RPG.
"""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from common.protocol import decode, encode


class Connection:
    """Uma conexão de cliente. `pid` é atribuído pela lógica de jogo após o join."""

    _next_id = 1

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader = reader
        self.writer = writer
        self.cid = Connection._next_id
        Connection._next_id += 1
        self.pid: int | None = None
        self.alive = True

    def send(self, msg: dict) -> None:
        """Envia uma mensagem (best-effort; falhas marcam a conexão como morta)."""
        if not self.alive:
            return
        try:
            self.writer.write(encode(msg))
        except Exception:
            self.alive = False

    async def drain(self) -> None:
        try:
            await self.writer.drain()
        except Exception:
            self.alive = False

    def close(self) -> None:
        self.alive = False
        try:
            self.writer.close()
        except Exception:
            pass


OnConnect = Callable[[Connection], Awaitable[None]]
OnMessage = Callable[[Connection, dict], Awaitable[None]]
OnDisconnect = Callable[[Connection], Awaitable[None]]


async def serve(host: str, port: int,
                on_connect: OnConnect,
                on_message: OnMessage,
                on_disconnect: OnDisconnect) -> asyncio.AbstractServer:
    """Inicia o servidor TCP e devolve o objeto Server (para .serve_forever())."""

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        conn = Connection(reader, writer)
        await on_connect(conn)
        try:
            while conn.alive:
                line = await reader.readline()
                if not line:  # EOF -> cliente desconectou
                    break
                try:
                    msg = decode(line)
                except Exception:
                    continue  # ignora linhas malformadas
                await on_message(conn, msg)
                await conn.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            conn.alive = False
            await on_disconnect(conn)
            conn.close()

    server = await asyncio.start_server(handle, host, port)
    return server
