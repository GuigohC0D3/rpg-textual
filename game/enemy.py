"""
Inimigos: carregamento do bestiário, instância em combate e IA simples.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from functools import lru_cache

from . import DATA_DIR


@lru_cache(maxsize=1)
def bestiary() -> dict[str, dict]:
    with open(DATA_DIR / "enemies.json", encoding="utf-8") as f:
        return json.load(f)


def enemies_for_region(region: str) -> list[str]:
    return [eid for eid, e in bestiary().items()
            if e["region"] == region and not e.get("boss")]


def bosses_for_region(region: str) -> list[str]:
    return [eid for eid, e in bestiary().items()
            if e["region"] == region and e.get("boss")]


@dataclass
class Enemy:
    """Instância viva de um inimigo (cópia do template, com HP mutável)."""
    eid: str
    name: str
    hp: int
    max_hp: int
    atk: int
    defense: int
    speed: int
    xp: int
    gold: int
    boss: bool = False
    skill: str | None = None
    art: str | None = None
    loot: list[str] = field(default_factory=list)

    @classmethod
    def spawn(cls, eid: str) -> "Enemy":
        t = bestiary()[eid]
        return cls(
            eid=eid, name=t["name"], hp=t["hp"], max_hp=t["hp"],
            atk=t["atk"], defense=t["def"], speed=t["speed"],
            xp=t["xp"], gold=t["gold"], boss=t.get("boss", False),
            skill=t.get("skill"), art=t.get("art"), loot=list(t.get("loot", [])),
        )

    def is_alive(self) -> bool:
        return self.hp > 0

    def choose_action(self) -> str:
        """IA simples: chefes usam habilidade ~35% das vezes; senão atacam."""
        if self.boss and self.skill and random.random() < 0.35:
            return "skill"
        return "attack"

    def roll_loot(self) -> str | None:
        """Chance de dropar um item da lista de loot."""
        if self.loot and random.random() < (0.6 if self.boss else 0.35):
            return random.choice(self.loot)
        return None
