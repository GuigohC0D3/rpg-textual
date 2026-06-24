"""
Definição das classes jogáveis e seus atributos base.

Para simplificar, todas as classes usam "mana" como recurso de habilidade.
Cada classe possui UMA habilidade ativa descrita por um dict:
  cost   -> mana gasta
  power  -> multiplicador sobre o ataque (ou cura)
  kind   -> "damage" (dano ao inimigo) | "heal" (cura no usuário/aliado)
"""
from __future__ import annotations

# Cada classe tem UMA habilidade (skill, barata) e UMA suprema (ult, cara, com
# recarga em turnos). Algumas aplicam efeitos de status (inflict) ao inimigo, ou
# em si mesmo (inflict_self), ampliando a profundidade tática do combate.
CLASSES: dict[str, dict] = {
    "Guerreiro": {
        "desc": "Muito HP, defesa alta e golpes pesados.",
        "hp": 140, "mana": 30, "atk": 18, "def": 12, "speed": 6, "crit": 0.05,
        "skill": {"name": "Golpe Brutal", "cost": 12, "power": 2.2, "kind": "damage"},
        "ult": {"name": "Fúria Sangrenta", "cost": 24, "power": 3.2, "kind": "damage",
                "cd": 3, "inflict": {"kind": "bleed", "power": 8, "turns": 3}},
        "start_item": "iron_sword",
    },
    "Mago": {
        "desc": "Dano mágico devastador e muita mana, porém frágil.",
        "hp": 75, "mana": 130, "atk": 9, "def": 4, "speed": 8, "crit": 0.10,
        "skill": {"name": "Bola de Fogo", "cost": 18, "power": 3.4, "kind": "damage",
                  "inflict": {"kind": "burn", "power": 6, "turns": 2}},
        "ult": {"name": "Meteoro", "cost": 40, "power": 4.6, "kind": "damage",
                "cd": 3, "inflict": {"kind": "burn", "power": 12, "turns": 3}},
        "start_item": "oak_staff",
    },
    "Arqueiro": {
        "desc": "Ataques rápidos à distância com alta chance crítica.",
        "hp": 95, "mana": 60, "atk": 14, "def": 7, "speed": 12, "crit": 0.25,
        "skill": {"name": "Tiro Certeiro", "cost": 14, "power": 2.6, "kind": "damage",
                  "inflict": {"kind": "bleed", "power": 5, "turns": 2}},
        "ult": {"name": "Chuva de Flechas", "cost": 30, "power": 3.4, "kind": "damage",
                "cd": 3, "inflict": {"kind": "bleed", "power": 7, "turns": 4}},
        "start_item": "short_bow",
    },
    "Curandeiro": {
        "desc": "Cura aliados, concede buffs e causa dano moderado.",
        "hp": 105, "mana": 110, "atk": 10, "def": 8, "speed": 9, "crit": 0.08,
        "skill": {"name": "Cura Divina", "cost": 16, "power": 2.8, "kind": "heal"},
        "ult": {"name": "Luz Restauradora", "cost": 34, "power": 3.6, "kind": "heal",
                "cd": 3, "inflict_self": {"kind": "regen", "power": 10, "turns": 3}},
        "start_item": "oak_staff",
    },
}

CLASS_NAMES = list(CLASSES.keys())
