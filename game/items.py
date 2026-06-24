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
    """IDs à venda na loja, ordenados por preço crescente."""
    stock = [iid for iid, it in all_items().items()
             if it.get("value") and (it["slot"] == "consumable"
                                      or it.get("rarity") in SHOP_RARITIES)]
    return sorted(stock, key=item_value)


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
