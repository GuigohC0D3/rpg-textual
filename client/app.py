"""
Cliente Textual do RPG.

Liga a TUI ao servidor via asyncio:
  * Um worker assíncrono mantém a conexão TCP, lê mensagens e atualiza a UI.
  * Reconexão automática com backoff exponencial em caso de queda.
  * Teclado: WASD/setas movem; 1-5 são ações de combate; Enter foca o chat.

Execução:  python -m client.app
"""
from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Input, RichLog

from common import protocol as P
from common.protocol import decode, encode

from .screens import ConnectScreen
from .widgets import CombatPanel, MapView, Sidebar

MOVE_KEYS = {
    "w": "n", "up": "n", "s": "s", "down": "s",
    "a": "w", "left": "w", "d": "e", "right": "e",
}
COMBAT_KEYS = {"1": "attack", "2": "defend", "3": "skill", "4": "item", "5": "flee"}


class GameScreen(Screen):
    """Tela principal: mapa, chat, ficha e combate, ligados ao servidor."""

    CSS = """
    #main { height: 1fr; }
    #left { width: 2fr; }
    #right { width: 46; }
    #map { height: 1fr; border: round green; padding: 0 1; }
    #chat { height: 12; border: round blue; }
    #side { height: 1fr; border: round yellow; padding: 0 1; }
    #combat { height: 13; border: round red; padding: 0 1; }
    #log { height: 10; border: round magenta; }
    #cmd { dock: bottom; }
    """

    def __init__(self, name: str, cls: str, host: str, port: int):
        super().__init__()
        self.pname = name
        self.pcls = cls
        self.host = host
        self.port = port
        self._writer: asyncio.StreamWriter | None = None
        self._closing = False
        self._in_combat = False

    def compose(self) -> ComposeResult:
        with Horizontal(id="main"):
            with Vertical(id="left"):
                yield MapView(id="map")
                yield RichLog(id="chat", markup=True, wrap=True)
            with Vertical(id="right"):
                yield Sidebar(id="side")
                yield CombatPanel(id="combat")
                yield RichLog(id="log", markup=True, wrap=True)
        yield Input(placeholder="Mensagem ou /comando (Enter envia, Esc volta)", id="cmd")

    def on_mount(self) -> None:
        self.set_focus(None)  # foco livre -> teclas vão para movimento
        self.query_one("#chat", RichLog).write("[cyan]Conectando ao servidor...[/]")
        self.run_worker(self._network(), exclusive=True)

    # ================= rede =================
    async def _network(self) -> None:
        backoff = 1
        while not self._closing:
            try:
                reader, writer = await asyncio.open_connection(self.host, self.port)
                self._writer = writer
                writer.write(encode({"t": P.C_JOIN, "name": self.pname, "cls": self.pcls}))
                await writer.drain()
                self._status("[green]Conectado.[/]")
                backoff = 1
                while not self._closing:
                    line = await reader.readline()
                    if not line:
                        break
                    self._dispatch(decode(line))
            except Exception as exc:  # falha de conexão -> reconectar
                self._status(f"[red]Sem conexão ({exc.__class__.__name__}). Reconectando...[/]")
            self._writer = None
            if self._closing:
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 8)

    def send_msg(self, msg: dict) -> None:
        if self._writer is not None:
            try:
                self._writer.write(encode(msg))
            except Exception:
                pass

    def _status(self, text: str) -> None:
        self.query_one("#chat", RichLog).write(text)

    # ================= mensagens do servidor =================
    def _dispatch(self, msg: dict) -> None:
        t = msg.get("t")
        if t in (P.S_WELCOME, P.S_YOU):
            self.query_one("#side", Sidebar).update_panel(msg["player"])
        elif t == P.S_STATE:
            self.query_one("#map", MapView).update_view(
                msg["view"], msg["daynight"], msg["weather"], msg["hour"])
        elif t == P.S_CHAT:
            color = {"private": "magenta", "global": "white"}.get(msg.get("scope"), "white")
            self.query_one("#chat", RichLog).write(
                f"[bold cyan]{msg['from']}:[/] [{color}]{msg['text']}[/]")
        elif t == P.S_LOG:
            self.query_one("#log", RichLog).write(msg["text"])
        elif t == P.S_COMBAT:
            self._in_combat = bool(msg.get("active"))
            self.query_one("#combat", CombatPanel).show(msg)
        elif t == P.S_ERROR:
            self.query_one("#chat", RichLog).write(f"[red]{msg['text']}[/]")

    # ================= teclado =================
    def on_key(self, event) -> None:
        # se o chat estiver focado, deixe o Input tratar as teclas
        if self.focused is not None:
            return
        key = event.key
        if key == "enter":
            self.set_focus(self.query_one("#cmd", Input))
            event.stop()
        elif self._in_combat and key in COMBAT_KEYS:
            self.send_msg({"t": P.C_COMBAT, "action": COMBAT_KEYS[key]})
            event.stop()
        elif key in MOVE_KEYS:
            self.send_msg({"t": P.C_MOVE, "dir": MOVE_KEYS[key]})
            event.stop()
        elif key == "r":
            self.send_msg({"t": P.C_ACTION, "cmd": "rest"})
            event.stop()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if text:
            self.send_msg({"t": P.C_CHAT, "text": text})
        event.input.value = ""
        self.set_focus(None)  # volta o foco para o movimento

    def key_escape(self) -> None:
        self.set_focus(None)


class RPGApp(App):
    TITLE = "RPG Textual Cooperativo"

    def on_mount(self) -> None:
        self.push_screen(ConnectScreen())

    def start_game(self, name: str, cls: str, host: str, port: int) -> None:
        self.push_screen(GameScreen(name, cls, host, port))


def main() -> None:
    RPGApp().run()


if __name__ == "__main__":
    main()
