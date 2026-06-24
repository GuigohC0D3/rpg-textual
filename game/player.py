"""
Personagem do jogador: stats, leveling, inventário, equipamento e persistência.

O Player é puramente de dados/regras — não conhece rede nem UI. O servidor é
a única autoridade que modifica instâncias de Player.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields

from . import SAVE_DIR
from .classes import CLASSES
from .items import EQUIP_SLOTS, get_item


def xp_to_next(level: int) -> int:
    """Curva de experiência simples e previsível."""
    return 50 + (level - 1) * 50


# Cores com que o jogador pode se identificar no mapa/ficha. São nomes válidos
# do Rich (funcionam ao renderar widgets, ao contrário do CSS do Textual).
PLAYER_COLORS = [
    "bright_white", "bright_red", "bright_green", "bright_yellow",
    "bright_blue", "bright_magenta", "bright_cyan", "orange1",
]
DEFAULT_COLOR = "bright_white"


def sanitize_color(color: str | None) -> str:
    """Garante que a cor recebida da rede é uma da paleta (evita markup malicioso)."""
    return color if color in PLAYER_COLORS else DEFAULT_COLOR


@dataclass
class Player:
    name: str
    cls: str
    level: int = 1
    xp: int = 0
    hp: int = 0
    max_hp: int = 0
    mana: int = 0
    max_mana: int = 0
    base_atk: int = 0
    base_def: int = 0
    base_speed: int = 0
    base_crit: float = 0.0
    gold: int = 25
    x: int = 0
    y: int = 0
    inventory: dict[str, int] = field(default_factory=dict)   # item_id -> qty
    equipment: dict[str, str] = field(default_factory=dict)   # slot -> item_id
    quests: dict[str, int] = field(default_factory=dict)      # quest_id -> progresso
    quests_done: list[str] = field(default_factory=list)
    party: str | None = None                                  # id do grupo
    guild: str | None = None                                  # nome da guilda
    pet: dict | None = None                                   # {"name", "atk"}
    color: str = DEFAULT_COLOR                                # cor de identificação no mapa
    upgrades: dict[str, int] = field(default_factory=dict)    # item_id -> nível de forja (+N)

    # ---- criação ----
    @classmethod
    def create(cls, name: str, klass: str, color: str = DEFAULT_COLOR) -> "Player":
        base = CLASSES[klass]
        p = cls(
            name=name, cls=klass, color=sanitize_color(color),
            max_hp=base["hp"], hp=base["hp"],
            max_mana=base["mana"], mana=base["mana"],
            base_atk=base["atk"], base_def=base["def"],
            base_speed=base["speed"], base_crit=base["crit"],
        )
        p.add_item(base["start_item"])
        p.add_item("health_potion", 3)
        p.add_item("mana_potion", 2)
        p.equip(base["start_item"])
        return p

    # ---- atributos efetivos (base + equipamento) ----
    # Cada nível de forja (+N) aumenta os bônus do item em 8%.
    FORGE_STEP = 0.08
    FORGE_MAX = 5

    def _equip_bonus(self, key: str) -> float:
        total = 0.0
        for item_id in self.equipment.values():
            it = get_item(item_id)
            if it and key in it:
                factor = 1 + self.FORGE_STEP * self.upgrades.get(item_id, 0)
                total += it[key] * factor
        return total

    @property
    def atk(self) -> int:
        return int(self.base_atk + self._equip_bonus("atk"))

    @property
    def defense(self) -> int:
        return int(self.base_def + self._equip_bonus("def"))

    @property
    def speed(self) -> int:
        return self.base_speed

    @property
    def crit(self) -> float:
        return round(self.base_crit + self._equip_bonus("crit"), 3)

    @property
    def skill(self) -> dict:
        return CLASSES[self.cls]["skill"]

    def refresh_maxes(self) -> None:
        """Recalcula HP/Mana máximos considerando bônus de equipamento."""
        base = CLASSES[self.cls]
        lvl_hp = base["hp"] + (self.level - 1) * 12
        lvl_mana = base["mana"] + (self.level - 1) * 8
        self.max_hp = int(lvl_hp + self._equip_bonus("hp"))
        self.max_mana = int(lvl_mana + self._equip_bonus("mana"))
        self.hp = min(self.hp, self.max_hp)
        self.mana = min(self.mana, self.max_mana)

    # ---- inventário ----
    def add_item(self, item_id: str, qty: int = 1) -> None:
        self.inventory[item_id] = self.inventory.get(item_id, 0) + qty

    def remove_item(self, item_id: str, qty: int = 1) -> bool:
        have = self.inventory.get(item_id, 0)
        if have < qty:
            return False
        if have == qty:
            del self.inventory[item_id]
        else:
            self.inventory[item_id] = have - qty
        return True

    def equip(self, item_id: str) -> bool:
        it = get_item(item_id)
        if not it or it["slot"] not in EQUIP_SLOTS:
            return False
        if self.inventory.get(item_id, 0) <= 0:
            return False
        slot = it["slot"]
        # devolve item já equipado ao inventário
        if slot in self.equipment:
            self.add_item(self.equipment[slot])
        self.remove_item(item_id)
        self.equipment[slot] = item_id
        self.refresh_maxes()
        return True

    def use_consumable(self, item_id: str) -> tuple[bool, str]:
        it = get_item(item_id)
        if not it or it["slot"] != "consumable":
            return False, "Item não consumível."
        if not self.remove_item(item_id):
            return False, "Você não possui esse item."
        msg = []
        if "heal" in it:
            healed = min(it["heal"], self.max_hp - self.hp)
            self.hp += healed
            msg.append(f"+{healed} HP")
        if "restore" in it:
            rest = min(it["restore"], self.max_mana - self.mana)
            self.mana += rest
            msg.append(f"+{rest} Mana")
        return True, f"{it['name']}: " + ", ".join(msg)

    # ---- progressão ----
    def gain_xp(self, amount: int) -> list[str]:
        logs = [f"+{amount} XP"]
        self.xp += amount
        while self.xp >= xp_to_next(self.level):
            self.xp -= xp_to_next(self.level)
            self.level += 1
            self.base_atk += 2
            self.base_def += 1
            if self.level % 3 == 0:
                self.base_speed += 1
            self.refresh_maxes()
            self.hp = self.max_hp
            self.mana = self.max_mana
            logs.append(f"⭐ Subiu para o nível {self.level}!")
        return logs

    def is_alive(self) -> bool:
        return self.hp > 0

    # ---- persistência ----
    def save(self) -> None:
        path = SAVE_DIR / f"{self.name.lower()}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, name: str) -> "Player | None":
        path = SAVE_DIR / f"{name.lower()}.json"
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        # tolera saves de versões diferentes: ignora chaves desconhecidas
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    # ---- visão para o cliente (painel lateral) ----
    def to_panel(self) -> dict:
        return {
            "name": self.name, "cls": self.cls, "level": self.level,
            "xp": self.xp, "xp_next": xp_to_next(self.level),
            "hp": self.hp, "max_hp": self.max_hp,
            "mana": self.mana, "max_mana": self.max_mana,
            "atk": self.atk, "def": self.defense,
            "crit": self.crit, "gold": self.gold,
            "inventory": self.inventory, "equipment": self.equipment,
            "skill": self.skill["name"],
            "quests": self.quests, "party": self.party,
            "guild": self.guild, "pet": self.pet, "color": self.color,
            "upgrades": self.upgrades,
        }
