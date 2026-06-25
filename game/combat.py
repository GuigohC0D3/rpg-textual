"""
Sistema de combate por turnos — cooperativo e autoritativo no servidor.

Modelo:
  Um Encounter representa a luta contra UM inimigo num tile. Vários jogadores
  podem participar (co-op): cada jogador envia uma ação; o servidor resolve a
  ação do jogador e, em seguida, o inimigo retalia contra quem agiu.

Ações do jogador: attack | defend | skill | ult | item | flee.

Efeitos de status (DoT/buff) adicionam profundidade:
  poison/burn/bleed -> dano por turno · regen -> cura por turno ·
  stun -> perde o turno · atk_up/def_up -> buff temporário (elixires).

Retorna sempre uma lista de logs (strings) para o servidor difundir.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from .classes import CLASSES
from .enemy import Enemy
from .items import get_item, item_name, item_value
from .player import Player


# Constante de mitigação: defesa reduz dano por % com retornos decrescentes.
# mitigação = def / (def + DEF_K). Ex.: def 50 -> 50% de redução.
DEF_K = 50

# Chance de um combatente paralisado perder o turno (estilo Pokémon).
PARALYZE_CHANCE = 0.30

# Rótulos legíveis de cada efeito de status.
STATUS_LABEL = {
    "poison": "veneno", "burn": "queimadura", "bleed": "sangramento",
    "regen": "regeneração", "stun": "atordoamento", "paralysis": "paralisia",
    "atk_up": "força", "def_up": "defesa",
}
DOT_KINDS = ("poison", "burn", "bleed")
# Status que controlam o turno e têm sua duração decrementada à parte (não em _tick).
DISABLE_KINDS = ("stun", "paralysis")


@dataclass
class Status:
    """Um efeito ativo sobre um combatente (jogador ou inimigo)."""
    kind: str
    turns: int
    power: float = 0.0

    @property
    def label(self) -> str:
        return STATUS_LABEL.get(self.kind, self.kind)


def make_status(kind: str, turns: int, power: float = 0.0) -> Status:
    return Status(kind=kind, turns=int(turns), power=float(power))


def _hit(atk: int, defense: int, crit: float = 0.0, mult: float = 1.0) -> tuple[int, bool]:
    """Dano = atk * (1 - mitigação) * multiplicador * variância(±15%), crítico x2."""
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
    pstatus: dict[int, list[Status]] = field(default_factory=dict)  # status por jogador
    estatus: list[Status] = field(default_factory=list)             # status no inimigo
    cooldowns: dict[int, int] = field(default_factory=dict)         # recarga da ult por pid

    def add(self, pid: int, player: Player) -> None:
        self.participants[pid] = player

    # ---- helpers de status ----
    @staticmethod
    def _apply(statuses: list[Status], s: Status) -> None:
        """Aplica/atualiza um status (substitui o de mesmo tipo, mantendo o melhor)."""
        for old in statuses:
            if old.kind == s.kind:
                old.turns = max(old.turns, s.turns)
                old.power = max(old.power, s.power)
                return
        statuses.append(s)

    @staticmethod
    def _buff(statuses: list[Status], kind: str) -> int:
        return int(sum(s.power for s in statuses if s.kind == kind))

    def _tick(self, statuses: list[Status], name: str) -> tuple[int, int, list[str]]:
        """Processa DoT/regen e decrementa duração (exceto stun). Retorna (dano, cura, logs)."""
        dmg = heal = 0
        logs: list[str] = []
        for s in list(statuses):
            if s.kind in DOT_KINDS:
                dmg += int(s.power)
                logs.append(f"  ☠ {name} sofre {int(s.power)} de {s.label}.")
            elif s.kind == "regen":
                heal += int(s.power)
                logs.append(f"  ✚ {name} regenera {int(s.power)}.")
            if s.kind not in DISABLE_KINDS:
                s.turns -= 1
                if s.turns <= 0:
                    statuses.remove(s)
        return dmg, heal, logs

    def _check_disable(self, statuses: list[Status], name: str) -> tuple[bool, list[str]]:
        """Atordoamento sempre faz perder o turno; paralisia tem chance (PARALYZE_CHANCE).

        Decrementa a duração desses status (chamado UMA vez por turno do combatente).
        Retorna (perdeu_turno, logs)."""
        logs: list[str] = []
        lost = False
        stun = next((s for s in statuses if s.kind == "stun"), None)
        if stun:
            lost = True
            logs.append(f"💫 {name} está atordoado e perde o turno!")
            stun.turns -= 1
            if stun.turns <= 0:
                statuses.remove(stun)
        para = next((s for s in statuses if s.kind == "paralysis"), None)
        if para:
            if not lost and random.random() < PARALYZE_CHANCE:
                lost = True
                logs.append(f"⚡ {name} está paralisado e não consegue se mover!")
            para.turns -= 1
            if para.turns <= 0:
                statuses.remove(para)
        return lost, logs

    def _inflict(self, statuses: list[Status], spec: dict | None, target: str) -> list[str]:
        if not spec:
            return []
        s = make_status(spec["kind"], spec["turns"], spec["power"])
        self._apply(statuses, s)
        return [f"  ✦ {target} recebe {s.label} ({s.turns} turnos)."]

    # ---- resolução de uma ação de um jogador ----
    def act(self, pid: int, action: str, item: str | None = None) -> list[str]:
        player = self.participants.get(pid)
        if player is None or self.finished or not player.is_alive():
            return []
        logs: list[str] = []
        pst = self.pstatus.setdefault(pid, [])

        # 1) DoT/regen do jogador no início do seu turno
        dmg, heal, dlogs = self._tick(pst, player.name)
        if dmg:
            player.hp = max(0, player.hp - dmg)
        if heal:
            player.hp = min(player.max_hp, player.hp + heal)
        logs += dlogs
        if not player.is_alive():
            player.hp = 0
            logs.append(f"💀 {player.name} sucumbiu aos ferimentos!")
            self.participants.pop(pid, None)
            self.pstatus.pop(pid, None)
            if not self.participants:
                self.finished = True
            return logs

        # 2) recarga da ult
        if self.cooldowns.get(pid, 0) > 0:
            self.cooldowns[pid] -= 1

        # 3) atordoamento/paralisia: pode perder o turno
        lost, dlogs = self._check_disable(pst, player.name)
        if lost:
            logs += dlogs
            logs += self._enemy_retaliate(pid)
            return logs

        atk_buff = self._buff(pst, "atk_up")

        # ⚡ velocidade decide a ordem: o mais rápido golpeia primeiro (estilo Pokémon).
        enemy_first = self.enemy.speed > player.speed
        if enemy_first:
            logs += self._enemy_retaliate(pid)
            if not player.is_alive() or self.finished:
                return logs

        if action == "attack":
            dmg, crit = _hit(player.atk + atk_buff, self.enemy.defense, player.crit)
            self.enemy.hp -= dmg
            logs.append(f"{player.name} ataca {self.enemy.name}: {dmg} dano"
                        + (" CRÍTICO!" if crit else ""))
            logs += self._pet_assist(player)

        elif action == "skill":
            logs += self._cast(player, pid, CLASSES[player.cls]["skill"], atk_buff)

        elif action == "ult":
            ult = CLASSES[player.cls]["ult"]
            if self.cooldowns.get(pid, 0) > 0:
                logs.append(f"{ult['name']} está em recarga ({self.cooldowns[pid]} turno(s)).")
                return logs
            logs += self._cast(player, pid, ult, atk_buff, is_ult=True)

        elif action == "defend":
            self.defending.add(pid)
            logs.append(f"{player.name} assume postura defensiva.")

        elif action == "item":
            logs += self._use_item(player, pst, item)

        elif action == "flee":
            if random.random() < 0.5 + player.speed * 0.02:
                self.participants.pop(pid, None)
                self.pstatus.pop(pid, None)
                logs.append(f"{player.name} fugiu do combate!")
                if not self.participants:
                    self.finished = True
                return logs
            logs.append(f"{player.name} tenta fugir... e falha!")

        # 4) DoT no inimigo após a ação do jogador
        edmg, _, elogs = self._tick(self.estatus, self.enemy.name)
        if edmg:
            self.enemy.hp -= edmg
        logs += elogs

        # vitória?
        if self.enemy.hp <= 0:
            self.finished = True
            self.victory = True
            logs += self._distribute_rewards()
            return logs

        # retaliação do inimigo (a menos que ele já tenha golpeado primeiro)
        if not enemy_first:
            logs += self._enemy_retaliate(pid)
        return logs

    def _cast(self, player: Player, pid: int, spec: dict, atk_buff: int,
              is_ult: bool = False) -> list[str]:
        """Resolve uma habilidade ou suprema (gasta mana, aplica efeitos)."""
        if player.mana < spec["cost"]:
            return [f"{player.name} não tem mana para {spec['name']}."]
        player.mana -= spec["cost"]
        if is_ult:
            self.cooldowns[pid] = spec["cd"]
        logs: list[str] = []
        if spec["kind"] == "heal":
            heal = int(player.atk * spec["power"])
            player.hp = min(player.max_hp, player.hp + heal)
            logs.append(f"{player.name} usa {spec['name']}: +{heal} HP")
            logs += self._inflict(self.pstatus.setdefault(pid, []),
                                  spec.get("inflict_self"), player.name)
        else:
            dmg, crit = _hit(player.atk + atk_buff, self.enemy.defense,
                             player.crit, spec["power"])
            self.enemy.hp -= dmg
            logs.append(f"{player.name} usa {spec['name']}: {dmg} dano"
                        + (" CRÍTICO!" if crit else ""))
            if self.enemy.hp > 0:
                logs += self._inflict(self.estatus, spec.get("inflict"), self.enemy.name)
            logs += self._pet_assist(player)
        return logs

    def _use_item(self, player: Player, pst: list[Status], item: str | None) -> list[str]:
        """Usa um consumível. Elixires de buff aplicam status; poções curam/restauram."""
        iid = item or "health_potion"
        it = get_item(iid)
        if it and it.get("buff"):
            if not player.remove_item(iid):
                return ["Você não possui esse item."]
            s = make_status(it["buff"], it.get("buff_turns", 3), it.get("buff_power", 10))
            self._apply(pst, s)
            return [f"{player.name} bebe {it['name']}: {s.label} +{int(s.power)} "
                    f"por {s.turns} turnos."]
        ok, msg = player.use_consumable(iid)
        return [msg]

    def _pet_assist(self, player: Player) -> list[str]:
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
        pst = self.pstatus.setdefault(pid, [])
        # o inimigo também pode estar atordoado/paralisado e perder o golpe
        lost, dlogs = self._check_disable(self.estatus, self.enemy.name)
        if lost:
            return dlogs
        e_action = self.enemy.choose_action()
        mult = 1.6 if e_action == "skill" else 1.0
        def_buff = self._buff(pst, "def_up")
        dmg, _ = _hit(self.enemy.atk, player.defense + def_buff, 0.0, mult)
        if pid in self.defending:
            dmg = max(1, dmg // 2)
            self.defending.discard(pid)
        player.hp -= dmg
        if e_action == "skill":
            verb = f"usa {self.enemy.skill}" if self.enemy.skill else "desfere um golpe especial em"
        else:
            verb = "ataca"
        logs.append(f"{self.enemy.name} {verb} {player.name}: {dmg} dano")
        # inimigos com aflição aplicam status ao usar habilidade
        if e_action == "skill" and self.enemy.ailment and player.is_alive():
            power = max(3, self.enemy.atk // 4)
            turns = 2 if self.enemy.ailment == "stun" else 3
            self._apply(pst, make_status(self.enemy.ailment, turns, power))
            logs.append(f"  ✦ {player.name} foi afligido: "
                        f"{STATUS_LABEL.get(self.enemy.ailment, self.enemy.ailment)}!")
        if not player.is_alive():
            player.hp = 0
            logs.append(f"💀 {player.name} foi derrotado!")
            self.participants.pop(pid, None)
            self.pstatus.pop(pid, None)
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
                plogs.append(f"🎁 Saque: {item_name(drop)}")
            # chefes garantem um item FORTE (o mais valioso da sua lista de loot)
            if (self.enemy.boss or self.enemy.world_boss) and self.enemy.loot:
                strong = max(self.enemy.loot, key=item_value)
                player.add_item(strong)
                plogs.append(f"⭐ Saque do chefe: {item_name(strong)}")
                if self.enemy.world_boss:               # tesouro extra do chefe de mundo
                    extra = random.choice(self.enemy.loot)
                    player.add_item(extra)
                    plogs.append(f"🏆 Tesouro do Chefe de Mundo: {item_name(extra)}")
            # elites e chefes soltam material de forja
            if (self.enemy.boss or self.enemy.elite) and random.random() < 0.7:
                player.add_item("monster_essence")
                plogs.append("🔩 Saque: monster_essence")
            plogs += quests.on_kill(player, self.enemy.eid)
            plogs += self._try_tame(player)
            self.rewards[pid] = plogs
        return global_logs

    def _try_tame(self, player: Player) -> list[str]:
        if self.enemy.boss or random.random() >= 0.12:
            return []
        new_atk = max(3, self.enemy.atk // 2)
        if player.pet and player.pet["atk"] >= new_atk:
            return []
        player.pet = {"name": f"{self.enemy.name} domado", "atk": new_atk}
        return [f"🐾 Você domou um {self.enemy.name}! Ele agora luta ao seu lado."]

    def state_for(self, pid: int) -> dict:
        """Estado do combate enviado ao cliente para renderizar o painel."""
        player = self.participants.get(pid)
        ult = CLASSES[player.cls]["ult"] if player else {"name": "—"}
        return {
            "active": not self.finished,
            "enemy": self.enemy.name,
            "enemy_hp": max(0, self.enemy.hp),
            "enemy_max_hp": self.enemy.max_hp,
            "boss": self.enemy.boss,
            "art": self.enemy.art,
            "enemy_speed": self.enemy.speed,
            "my_speed": player.speed if player else 0,
            "enemy_first": bool(player and self.enemy.speed > player.speed),
            "allies": [p.name for p in self.participants.values()],
            "enemy_status": [s.label for s in self.estatus],
            "my_status": [f"{s.label}·{s.turns}" for s in self.pstatus.get(pid, [])],
            "ult_name": ult["name"],
            "ult_cd": self.cooldowns.get(pid, 0),
        }
