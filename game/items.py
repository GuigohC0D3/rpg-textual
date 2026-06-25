"""
Carregamento de itens e helpers de equipamento/raridade.

Um item é um dict vindo de data/items.json. Slots de equipamento:
  weapon, armor, shield, amulet, ring  -> equipáveis
  consumable                            -> usável em combate/fora dele

Bônus possíveis: atk, def, hp, mana, crit, heal, restore.
"""
from __future__ import annotations

import json
from functools import lru_cache

from . import DATA_DIR

EQUIP_SLOTS = ("weapon", "armor", "shield", "amulet", "ring")

RARITY_COLOR = {
    "comum": "white",
    "raro": "cyan",
    "epico": "magenta",
    "lendario": "yellow",
}


@lru_cache(maxsize=1)
def all_items() -> dict[str, dict]:
    """Catálogo completo de itens (cacheado)."""
    with open(DATA_DIR / "items.json", encoding="utf-8") as f:
        return json.load(f)


def get_item(item_id: str) -> dict | None:
    return all_items().get(item_id)


def item_name(item_id: str) -> str:
    it = get_item(item_id)
    return it["name"] if it else item_id


def is_equippable(item_id: str) -> bool:
    it = get_item(item_id)
    return bool(it) and it["slot"] in EQUIP_SLOTS


def item_value(item_id: str) -> int:
    """Valor base de mercado do item (0 se não tiver preço)."""
    it = get_item(item_id)
    return int(it.get("value", 0)) if it else 0


# A loja vende consumíveis e equipamentos comuns/raros; épicos e lendários
# permanecem exclusivos de loot/drop para preservar a progressão.
SHOP_RARITIES = ("comum", "raro")


def shop_catalog() -> list[str]:
    """IDs à venda na loja, ordenados por preço crescente.

    Vende consumíveis e equipamentos comuns/raros. Materiais de forja e itens
    épicos/lendários ficam de fora (só por loot)."""
    stock = [iid for iid, it in all_items().items()
             if it.get("value") and (
                 it["slot"] == "consumable"
                 or (it["slot"] in EQUIP_SLOTS and it.get("rarity") in SHOP_RARITIES))]
    return sorted(stock, key=item_value)


# Rótulos curtos de cada bônus, para exibir dano/defesa nas listas da UI.
STAT_LABELS = {
    "atk": "ATK", "def": "DEF", "hp": "HP", "mana": "MP",
    "crit": "Crít", "heal": "Cura", "restore": "Mana",
}

# Atributo "principal" de cada slot — usado para comparar equipamentos (▲/▼).
SLOT_PRIMARY = {"weapon": "atk", "armor": "def", "shield": "def",
                "amulet": "crit", "ring": "atk"}


def stat_summary(item_id: str) -> str:
    """Resumo curto dos bônus do item (ex.: 'ATK 8' ou 'DEF 10, HP 30')."""
    it = get_item(item_id)
    if not it:
        return ""
    parts = []
    for k in ("atk", "def", "hp", "mana", "crit", "heal", "restore"):
        if k in it:
            v = it[k]
            parts.append(f"{STAT_LABELS[k]} +{int(v * 100)}%" if k == "crit"
                         else f"{STAT_LABELS[k]} {v}")
    return ", ".join(parts)


def compare_to_equipped(item_id: str, equipment: dict[str, str]) -> str:
    """Seta ▲/▼ comparando o atributo principal do item ao já equipado no slot."""
    it = get_item(item_id)
    if not it:
        return ""
    key = SLOT_PRIMARY.get(it.get("slot"))
    cur_id = equipment.get(it.get("slot")) if key else None
    if not key or not cur_id:
        return ""
    diff = it.get(key, 0) - (get_item(cur_id) or {}).get(key, 0)
    if not diff:
        return ""
    fmt = f"{int(diff * 100):+d}% {STAT_LABELS[key]}" if key == "crit" else f"{diff:+d} {STAT_LABELS[key]}"
    return ("  ▲" if diff > 0 else "  ▼") + fmt


def describe(item_id: str) -> str:
    """Texto curto com nome, raridade e bônus — usado em logs/inventário."""
    it = get_item(item_id)
    if not it:
        return item_id
    bonus = []
    for k in ("atk", "def", "hp", "mana", "crit", "heal", "restore"):
        if k in it:
            v = it[k]
            bonus.append(f"{k}+{int(v*100)}%" if k == "crit" else f"{k}+{v}")
    suffix = f" ({', '.join(bonus)})" if bonus else ""
    return f"{it['name']} [{it['rarity']}]{suffix}"
