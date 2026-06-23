"""
Sistema de missões (kill/boss quests) com rastreamento por jogador.

O progresso fica em Player.quests {quest_id: kills}. Ao completar, a recompensa
é entregue e o id vai para Player.quests_done.
"""
from __future__ import annotations

import json
from functools import lru_cache

from . import DATA_DIR
from .player import Player


@lru_cache(maxsize=1)
def all_quests() -> dict[str, dict]:
    with open(DATA_DIR / "quests.json", encoding="utf-8") as f:
        return json.load(f)


def offer(player: Player, quest_id: str) -> str | None:
    """Aceita uma missão se ainda não estiver ativa/concluída."""
    q = all_quests().get(quest_id)
    if not q or quest_id in player.quests or quest_id in player.quests_done:
        return None
    player.quests[quest_id] = 0
    return f"📜 Missão aceita: {q['name']} — {q['desc']}"


def on_kill(player: Player, enemy_id: str) -> list[str]:
    """Atualiza missões ativas quando o jogador derrota um inimigo."""
    logs: list[str] = []
    for qid, progress in list(player.quests.items()):
        q = all_quests()[qid]
        if q["target"] != enemy_id:
            continue
        progress += 1
        player.quests[qid] = progress
        if progress >= q["count"]:
            logs += _complete(player, qid, q)
        else:
            logs.append(f"📜 {q['name']}: {progress}/{q['count']}")
    return logs


def _complete(player: Player, qid: str, q: dict) -> list[str]:
    del player.quests[qid]
    player.quests_done.append(qid)
    player.gold += q["gold"]
    logs = [f"✅ Missão concluída: {q['name']} (+{q['gold']} ouro)"]
    if q.get("reward_item"):
        player.add_item(q["reward_item"])
        logs.append(f"🎁 Recompensa: {q['reward_item']}")
    logs += player.gain_xp(q["xp"])
    return logs
