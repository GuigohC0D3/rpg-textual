"""
Estado de jogo do servidor (autoritativo).

Agrega o mapa procedural, as sessões conectadas, combates ativos, grupos
(parties), clima e ciclo dia/noite. Contém helpers de consulta/visão, mas a
orquestração (rede, broadcast, tick) fica em server.py.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from game.combat import Encounter
from game.guild import GuildRegistry
from game.map import REGIONS, World
from game.player import Player

WEATHERS = ["Ensolarado", "Nublado", "Chuvoso", "Tempestade", "Neblina"]


@dataclass
class Session:
    """Um jogador conectado: liga pid <-> Player <-> conexão de rede."""
    pid: int
    player: Player
    conn: object                  # network.Connection (evita import circular)
    connected: bool = True
    view_hw: int = 12             # meia-largura da janela do mapa (tiles)
    view_hh: int = 6              # meia-altura da janela do mapa (tiles)


@dataclass
class Party:
    pid_leader: int
    members: set[int] = field(default_factory=set)


class GameState:
    def __init__(self, seed: int | None = None):
        self.world = World(seed=seed)
        self.sessions: dict[int, Session] = {}        # pid -> Session
        self.encounters: dict[tuple[int, int], Encounter] = {}  # pos -> luta
        self.parties: dict[int, Party] = {}           # party_id -> Party
        self._next_party = 1
        self.weather = random.choice(WEATHERS)
        self.time_of_day = 8                          # 0..23 (horas)
        self.guilds = GuildRegistry()                 # registro persistente de guildas
        self.xp_mult = 1.0                            # multiplicador global de XP (eventos)
        self.xp_event_ticks = 0                       # ticks restantes da bênção de XP
        self.world_boss_pos: tuple[int, int] | None = None  # posição do chefe de mundo ativo

    # ---- sessões ----
    def players_at(self, x: int, y: int) -> list[Session]:
        return [s for s in self.sessions.values()
                if s.player.x == x and s.player.y == y and s.connected]

    def online_names(self) -> list[str]:
        return [s.player.name for s in self.sessions.values() if s.connected]

    # ---- visão do mundo para um jogador (janela ao redor) ----
    def view_for(self, pid: int) -> dict:
        s = self.sessions[pid]
        px, py = s.player.x, s.player.y
        hw, hh = s.view_hw, s.view_hh
        me_color = s.player.color
        rows = []
        for y in range(py - hh, py + hh + 1):
            row = []
            for x in range(px - hw, px + hw + 1):
                row.append(self._cell(x, y, px, py, me_color))
            rows.append(row)
        return {
            "rows": rows,
            "region": self.world.region_at(px, py),
            "pos": [px, py],
        }

    def _cell(self, x: int, y: int, px: int, py: int, me_color: str = "bright_white") -> dict:
        """Descreve um tile: terreno, ocupantes (jogadores/inimigos)."""
        if not self.world.in_bounds(x, y):
            return {"ch": " ", "color": "black"}
        if x == px and y == py:
            return {"ch": "@", "color": me_color}             # você, na sua cor
        others = self.players_at(x, y)
        if others:
            return {"ch": "P", "color": others[0].player.color}  # outro jogador, na cor dele
        if (x, y) in self.world.enemies:
            e = self.world.enemies[(x, y)]
            return {"ch": "&" if e.boss else "e",
                    "color": "bright_red" if e.boss else "red"}
        region = self.world.region_at(x, y)
        meta = REGIONS[region]
        return {"ch": meta["tile"], "color": meta["color"]}

    # ---- parties ----
    def create_party(self, leader_pid: int) -> int:
        pid_party = self._next_party
        self._next_party += 1
        self.parties[pid_party] = Party(leader_pid, {leader_pid})
        self.sessions[leader_pid].player.party = str(pid_party)
        return pid_party

    def party_members(self, pid: int) -> list[int]:
        s = self.sessions.get(pid)
        if not s or not s.player.party:
            return [pid]
        party = self.parties.get(int(s.player.party))
        return list(party.members) if party else [pid]
