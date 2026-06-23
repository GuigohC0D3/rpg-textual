"""
Sistema de combate por turnos — cooperativo e autoritativo no servidor.

Modelo:
  Um Encounter representa a luta contra UM inimigo num tile. Vários jogadores
  podem participar (co-op): cada jogador envia uma ação; o servidor resolve a
  ação do jogador e, em seguida, o inimigo retalia contra quem agiu.

Ações do jogador: attack | defend | skill | item | flee.
Retorna sempre uma lista de logs (strings) para o servidor difundir.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from .enemy import Enemy
from .player import Player


# Constante de mitigação: defesa reduz dano por % com retornos decrescentes.
# mitigação = def / (def + DEF_K). Ex.: def 50 -> 50% de redução.
DEF_K = 50


def _hit(atk: int, defense: int, crit: float = 0.0, mult: float = 1.0) -> tuple[int, bool]:
    """
    Dano = atk * (1 - mitigação) * multiplicador * variância(±15%), crítico x2.

    A mitigação percentual mantém a defesa relevante em todos os níveis sem
    nunca zerar o dano (ao contrário da subtração linear antiga, que tornava
    personagens com muita defesa praticamente imortais)."""
    mitigation = defense / (defense + DEF_K)
    dmg = atk * (1 - mitigation) * mult * random.uniform(0.85, 1.15)
    is_crit = random.random() < crit
    if is_crit:
        dmg *= 2
    return max(1, int(dmg)), is_crit


@dataclass
class Encounter:
    enemy: Enemy
    pos: tuple[int, int]
    participants: dict[int, Player] = field(default_factory=dict)  # pid -> Player
    defending: set[int] = field(default_factory=set)
    finished: bool = False
    victory: bool = False
    rewards: dict[int, list[str]] = field(default_factory=dict)    # logs por pid
    xp_mult: float = 1.0                                           # bônus de evento global

    def add(self, pid: int, player: Player) -> None:
        self.participants[pid] = player

    # ---- resolução de uma ação de um jogador ----
    def act(self, pid: int, action: str, item: str | None = None) -> list[str]:
        player = self.participants.get(pid)
        if player is None or self.finished or not player.is_alive():
            return []
        logs: list[str] = []

        if action == "attack":
            dmg, crit = _hit(player.atk, self.enemy.defense, player.crit)
            self.enemy.hp -= dmg
            logs.append(f"{player.name} ataca {self.enemy.name}: {dmg} dano"
                        + (" CRÍTICO!" if crit else ""))
            logs += self._pet_assist(player)

        elif action == "skill":
            sk = player.skill
            if player.mana < sk["cost"]:
                logs.append(f"{player.name} não tem mana para {sk['name']}.")
            else:
                player.mana -= sk["cost"]
                if sk["kind"] == "heal":
                    heal = int(player.atk * sk["power"])
                    player.hp = min(player.max_hp, player.hp + heal)
                    logs.append(f"{player.name} usa {sk['name']}: +{heal} HP")
                else:
                    dmg, crit = _hit(player.atk, self.enemy.defense, player.crit, sk["power"])
                    self.enemy.hp -= dmg
                    logs.append(f"{player.name} usa {sk['name']}: {dmg} dano"
                                + (" CRÍTICO!" if crit else ""))
                    logs += self._pet_assist(player)

        elif action == "defend":
            self.defending.add(pid)
            logs.append(f"{player.name} assume postura defensiva.")

        elif action == "item":
            ok, msg = player.use_consumable(item or "health_potion")
            logs.append(msg)

        elif action == "flee":
            if random.random() < 0.5 + player.speed * 0.02:
                self.participants.pop(pid, None)
                logs.append(f"{player.name} fugiu do combate!")
                if not self.participants:
                    self.finished = True
                return logs
            logs.append(f"{player.name} tenta fugir... e falha!")

        # vitória?
        if self.enemy.hp <= 0:
            self.finished = True
            self.victory = True
            logs += self._distribute_rewards()
            return logs

        # retaliação do inimigo contra quem agiu
        logs += self._enemy_retaliate(pid)
        return logs

    def _pet_assist(self, player: Player) -> list[str]:
        """Se o jogador tiver um pet, ele ataca o inimigo junto."""
        pet = player.pet
        if not pet or self.enemy.hp <= 0:
            return []
        dmg, crit = _hit(pet["atk"], self.enemy.defense, 0.05)
        self.enemy.hp -= dmg
        return [f"  🐾 {pet['name']} ataca: {dmg} dano" + (" CRÍTICO!" if crit else "")]

    def _enemy_retaliate(self, pid: int) -> list[str]:
        player = self.participants.get(pid)
        if player is None or not player.is_alive():
            return []
        logs: list[str] = []
        e_action = self.enemy.choose_action()
        mult = 1.6 if e_action == "skill" else 1.0
        dmg, _ = _hit(self.enemy.atk, player.defense, 0.0, mult)
        if pid in self.defending:
            dmg = max(1, dmg // 2)
            self.defending.discard(pid)
        player.hp -= dmg
        verb = f"usa {self.enemy.skill}" if e_action == "skill" else "ataca"
        logs.append(f"{self.enemy.name} {verb} {player.name}: {dmg} dano")
        if not player.is_alive():
            player.hp = 0
            logs.append(f"💀 {player.name} foi derrotado!")
            self.participants.pop(pid, None)
            if not self.participants:
                self.finished = True
        return logs

    def _distribute_rewards(self) -> list[str]:
        """XP/ouro divididos entre os participantes; loot rolado individualmente."""
        from . import quests
        global_logs = [f"🏆 {self.enemy.name} foi derrotado!"]
        n = max(1, len(self.participants))
        xp_each = max(1, int(self.enemy.xp * self.xp_mult) // n)
        gold_each = max(1, self.enemy.gold // n)
        for pid, player in self.participants.items():
            plogs = [f"+{gold_each} ouro"]
            player.gold += gold_each
            plogs += player.gain_xp(xp_each)
            drop = self.enemy.roll_loot()
            if drop:
                player.add_item(drop)
                plogs.append(f"🎁 Saque: {drop}")
            plogs += quests.on_kill(player, self.enemy.eid)
            plogs += self._try_tame(player)
            self.rewards[pid] = plogs
        return global_logs

    def _try_tame(self, player: Player) -> list[str]:
        """Chance de domar um inimigo comum derrotado, virando pet do jogador."""
        if self.enemy.boss or random.random() >= 0.12:
            return []
        new_atk = max(3, self.enemy.atk // 2)
        # só substitui o pet atual se o novo for mais forte
        if player.pet and player.pet["atk"] >= new_atk:
            return []
        player.pet = {"name": f"{self.enemy.name} domado", "atk": new_atk}
        return [f"🐾 Você domou um {self.enemy.name}! Ele agora luta ao seu lado."]

    def state_for(self, pid: int) -> dict:
        """Estado do combate enviado ao cliente para renderizar o painel."""
        return {
            "active": not self.finished,
            "enemy": self.enemy.name,
            "enemy_hp": max(0, self.enemy.hp),
            "enemy_max_hp": self.enemy.max_hp,
            "boss": self.enemy.boss,
            "art": self.enemy.art,
            "allies": [p.name for p in self.participants.values()],
        }
