"""
Telas do cliente. A ConnectScreen coleta nome, classe, IP e porta antes de
entrar na partida (GameScreen vive em app.py para ficar perto da rede).
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Center, Vertical
from textual.screen import Screen
from textual.widgets import Button, Input, Label, RadioButton, RadioSet, Static

from game.classes import CLASSES


class ConnectScreen(Screen):
    """Lobby: configura personagem e endereço do servidor."""

    CSS = """
    ConnectScreen { align: center middle; }
    #box { width: 64; height: auto; border: round cyan; padding: 1 2; }
    #title { text-align: center; color: cyan; text-style: bold; }
    Input { margin: 1 0; }
    RadioSet { height: auto; margin: 1 0; }
    Button { margin-top: 1; width: 100%; }
    .hint { color: #888888; }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="box"):
            yield Static("⚔  RPG TEXTUAL COOPERATIVO  ⚔", id="title")
            yield Static("Hospedar: rode 'python -m server.server' e use seu IP da LAN.",
                         classes="hint")
            yield Input(placeholder="Nome do herói", id="name")
            yield Label("Classe:")
            with RadioSet(id="cls"):
                for i, (name, data) in enumerate(CLASSES.items()):
                    yield RadioButton(f"{name} — {data['desc']}", value=(i == 0))
            yield Input(value="127.0.0.1", placeholder="IP do servidor", id="host")
            yield Input(value="7777", placeholder="Porta", id="port")
            yield Button("Entrar na Aventura", variant="success", id="go")
            yield Static("", id="err", classes="hint")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self._connect()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._connect()

    def _connect(self) -> None:
        name = self.query_one("#name", Input).value.strip()
        host = self.query_one("#host", Input).value.strip() or "127.0.0.1"
        port_raw = self.query_one("#port", Input).value.strip()
        cls_idx = self.query_one("#cls", RadioSet).pressed_index
        cls_name = list(CLASSES.keys())[max(0, cls_idx)]
        if not name:
            self.query_one("#err", Static).update("Informe um nome.")
            return
        try:
            port = int(port_raw)
        except ValueError:
            self.query_one("#err", Static).update("Porta inválida.")
            return
        self.app.start_game(name, cls_name, host, port)
