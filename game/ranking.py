"""
Ranking de jogadores: combina personagens online (estado ao vivo) com os
salvos em disco (offline), ordenando por nível e depois por XP.
"""
from __future__ import annotations

import json

from . import SAVE_DIR


def leaderboard(live: dict[str, dict], top: int = 10) -> list[dict]:
    """
    `live` = {nome_lower: {"name","cls","level","xp","gold"}} dos jogadores online.
    Saves em disco preenchem os offline. Online tem prioridade (mais atual).
    """
    entries: dict[str, dict] = {}
    for path in SAVE_DIR.glob("*.json"):
        if path.name == "guilds.json":
            continue
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            entries[d["name"].lower()] = {
                "name": d["name"], "cls": d["cls"], "level": d["level"],
                "xp": d["xp"], "gold": d["gold"],
            }
        except Exception:
            continue
    entries.update(live)  # sobrescreve com dados ao vivo
    ranked = sorted(entries.values(), key=lambda e: (e["level"], e["xp"]), reverse=True)
    return ranked[:top]
