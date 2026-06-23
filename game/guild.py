"""
Guildas persistentes (registro global, separado dos personagens).

Armazenadas em save/guilds.json como {nome: {"leader": str, "members": [str]}}.
Os jogadores guardam apenas o nome da guilda em Player.guild.
"""
from __future__ import annotations

import json

from . import SAVE_DIR

_PATH = SAVE_DIR / "guilds.json"


class GuildRegistry:
    def __init__(self) -> None:
        self.guilds: dict[str, dict] = {}
        self.load()

    def load(self) -> None:
        if _PATH.exists():
            with open(_PATH, encoding="utf-8") as f:
                self.guilds = json.load(f)

    def save(self) -> None:
        with open(_PATH, "w", encoding="utf-8") as f:
            json.dump(self.guilds, f, ensure_ascii=False, indent=2)

    def create(self, name: str, leader: str) -> tuple[bool, str]:
        if name in self.guilds:
            return False, "Já existe uma guilda com esse nome."
        if self.find_player(leader):
            return False, "Você já pertence a uma guilda (use /guild leave)."
        self.guilds[name] = {"leader": leader, "members": [leader]}
        self.save()
        return True, f"🏰 Guilda '{name}' fundada!"

    def add_member(self, name: str, player: str) -> tuple[bool, str]:
        g = self.guilds.get(name)
        if not g:
            return False, "Guilda inexistente."
        if self.find_player(player):
            return False, "Você já pertence a uma guilda."
        g["members"].append(player)
        self.save()
        return True, f"Você entrou na guilda '{name}'."

    def leave(self, player: str) -> tuple[bool, str]:
        name = self.find_player(player)
        if not name:
            return False, "Você não está em nenhuma guilda."
        g = self.guilds[name]
        g["members"].remove(player)
        if g["leader"] == player:  # líder saiu -> dissolve ou repassa
            if g["members"]:
                g["leader"] = g["members"][0]
            else:
                del self.guilds[name]
        self.save()
        return True, f"Você saiu da guilda '{name}'."

    def find_player(self, player: str) -> str | None:
        for name, g in self.guilds.items():
            if player in g["members"]:
                return name
        return None

    def info(self, name: str) -> str | None:
        g = self.guilds.get(name)
        if not g:
            return None
        return (f"🏰 {name} (líder: {g['leader']}) — "
                f"{len(g['members'])} membros: {', '.join(g['members'])}")

    def list_names(self) -> list[str]:
        return [f"{n} ({len(g['members'])})" for n, g in self.guilds.items()]
