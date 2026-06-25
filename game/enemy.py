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


# Modificadores de elite: prefixo de nome + multiplicadores de atributo + aflição.
ELITE_MODS = {
    "Veloz":     {"atk": 1.10, "speed": 1.8},
    "Blindado":  {"def": 2.0, "hp": 1.4},
    "Venenoso":  {"atk": 1.05, "ailment": "poison"},
    "Brutal":    {"atk": 1.30, "ailment": "stun"},
    "Paralisante": {"atk": 1.05, "speed": 1.3, "ailment": "paralysis"},
    "Colossal":  {"hp": 1.8, "atk": 1.25},
}


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
    level: int = 1
    elite: str | None = None        # nome do modificador de elite, se houver
    ailment: str | None = None      # status que aplica ao usar habilidade
    world_boss: bool = False

    @classmethod
    def spawn(cls, eid: str, level: int = 1, elite: str | None = None) -> "Enemy":
        t = bestiary()[eid]
        # escala por nível: inimigos longe da Vila são bem mais perigosos
        lf = 1 + 0.18 * (level - 1)          # fator p/ HP
        af = 1 + 0.12 * (level - 1)          # fator p/ ATK/DEF
        rf = 1 + 0.25 * (level - 1)          # fator p/ recompensa
        hp = t["hp"] * lf
        atk = t["atk"] * af
        dfs = t["def"] * af
        speed = t["speed"]
        xp = t["xp"] * rf
        gold = t["gold"] * rf
        name = t["name"]
        ailment = t.get("ailment")

        mod = ELITE_MODS.get(elite or "")
        if mod:
            hp *= mod.get("hp", 1.0)
            atk *= mod.get("atk", 1.0)
            dfs *= mod.get("def", 1.0)
            speed = int(speed * mod.get("speed", 1.0))
            xp *= 1.6
            gold *= 1.6
            ailment = mod.get("ailment", ailment)
            name = f"{name} {elite}"

        hp = int(hp)
        return cls(
            eid=eid, name=name, hp=hp, max_hp=hp,
            atk=max(1, int(atk)), defense=int(dfs), speed=speed,
            xp=max(1, int(xp)), gold=max(1, int(gold)), boss=t.get("boss", False),
            skill=t.get("skill"), art=t.get("art"), loot=list(t.get("loot", [])),
            level=max(1, level), elite=elite, ailment=ailment,
        )

    def is_alive(self) -> bool:
        return self.hp > 0

    def choose_action(self) -> str:
        """IA: chefes e inimigos com aflição usam habilidade às vezes; senão atacam."""
        if self.skill and (self.boss or self.world_boss) and random.random() < 0.35:
            return "skill"
        if self.ailment and random.random() < 0.30:
            return "skill"
        return "attack"

    def roll_loot(self) -> str | None:
        """Chance de dropar um item da lista de loot."""
        if self.loot and random.random() < (0.6 if self.boss else 0.35):
            return random.choice(self.loot)
        return None
