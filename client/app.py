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

    # Bindings disparam quando o widget focado NÃO consome a tecla.
    # Com o chat (Input) desfocado, mover/combater funciona; com ele focado,
    # o Input consome letras/números e as bindings não interferem na digitação.
    BINDINGS = [
        ("w,up", "move('n')", "Norte"),
        ("s,down", "move('s')", "Sul"),
        ("a,left", "move('w')", "Oeste"),
        ("d,right", "move('e')", "Leste"),
        ("1", "combat('attack')", "Atacar"),
        ("2", "combat('defend')", "Defender"),
        ("3", "combat('skill')", "Habilidade"),
        ("4", "combat('item')", "Poção"),
        ("5", "combat('flee')", "Fugir"),
        ("6", "combat('ult')", "Suprema"),
        ("r", "rest", "Descansar"),
        ("enter", "focus_chat", "Chat"),
        ("escape", "unfocus_chat", "Voltar"),
    ]

    def __init__(self, name: str, cls: str, color: str, host: str, port: int):
        super().__init__()
        self.pname = name
        self.pcls = cls
        self.pcolor = color
        self.host = host
        self.port = port
        self._writer: asyncio.StreamWriter | None = None
        self._closing = False
        self._in_combat = False

    def compose(self) -> ComposeResult:
        with Horizontal(id="main"):
            with Vertical(id="left"):
                yield MapView(id="map")
                # can_focus=False (atributo de instância): os logs não roubam o
                # foco nem capturam as setas. Não é aceito como kwarg do __init__.
                chat = RichLog(id="chat", markup=True, wrap=True)
                chat.can_focus = False
                yield chat
            with Vertical(id="right"):
                yield Sidebar(id="side")
                yield CombatPanel(id="combat")
                log = RichLog(id="log", markup=True, wrap=True)
                log.can_focus = False
                yield log
        yield Input(placeholder="Mensagem ou /comando (Enter envia, Esc volta)", id="cmd")

    def on_mount(self) -> None:
        # Desfoca o Input após o refresh inicial: começamos no "modo movimento".
        self.call_after_refresh(lambda: self.set_focus(None))
        self.query_one("#chat", RichLog).write("[cyan]Conectando ao servidor...[/]")
        self.run_worker(self._network(), exclusive=True)

    # ================= rede =================
    async def _network(self) -> None:
        backoff = 1
        while not self._closing:
            try:
                reader, writer = await asyncio.open_connection(self.host, self.port)
                self._writer = writer
                writer.write(encode({"t": P.C_JOIN, "name": self.pname,
                                     "cls": self.pcls, "color": self.pcolor}))
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
            if t == P.S_WELCOME:
                # já conectado e com layout pronto: pede a janela do tamanho do painel
                self.query_one("#map", MapView).send_viewport()
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

    # ================= teclado (actions das BINDINGS) =================
    def action_move(self, direction: str) -> None:
        self.send_msg({"t": P.C_MOVE, "dir": direction})

    def action_combat(self, combat_action: str) -> None:
        if self._in_combat:
            self.send_msg({"t": P.C_COMBAT, "action": combat_action})
        elif combat_action == "item":
            # fora de combate, a tecla de poção usa uma Poção de Vida rápida
            self.send_msg({"t": P.C_ACTION, "cmd": "potion"})

    def action_rest(self) -> None:
        self.send_msg({"t": P.C_ACTION, "cmd": "rest"})

    def action_focus_chat(self) -> None:
        self.set_focus(self.query_one("#cmd", Input))

    def action_unfocus_chat(self) -> None:
        self.set_focus(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if text:
            self.send_msg({"t": P.C_CHAT, "text": text})
        event.input.value = ""
        self.set_focus(None)  # volta para o "modo movimento"


class RPGApp(App):
    TITLE = "RPG Textual Cooperativo"

    def on_mount(self) -> None:
        self.push_screen(ConnectScreen())

    def start_game(self, name: str, cls: str, color: str, host: str, port: int) -> None:
        self.push_screen(GameScreen(name, cls, color, host, port))


def main() -> None:
    RPGApp().run()


if __name__ == "__main__":
    main()
