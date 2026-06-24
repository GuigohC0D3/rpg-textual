"""
Servidor de jogo — orquestração completa.

Responsabilidades:
  * Receber mensagens dos clientes (via network.serve) e despachá-las.
  * Manter o estado autoritativo (GameState) e difundir atualizações.
  * Rodar o "tick" do mundo: ciclo dia/noite, clima, respawn e autosave.

Execução:  python -m server.server [host] [port]
Padrão:    host 0.0.0.0  port 7777  (acessível na LAN)
"""
from __future__ import annotations

import asyncio
import random
import sys
from dataclasses import dataclass, field

from common import protocol as P
from game.combat import Encounter
from game.items import (describe, get_item, is_equippable, item_name,
                        item_value, shop_catalog)
from game.map import REGIONS
from game.player import Player, sanitize_color
from game.quests import all_quests, offer
from game.ranking import leaderboard

from .network import Connection, serve
from .world import WEATHERS, GameState, Session

MOVES = {"n": (0, -1), "s": (0, 1), "e": (1, 0), "w": (-1, 0)}


@dataclass
class TradeSession:
    """Troca ativa entre dois jogadores. Cada lado monta uma oferta e ambos
    precisam confirmar; qualquer alteração na oferta zera as confirmações."""
    a: int
    b: int
    offer: dict = field(default_factory=dict)        # pid -> {"gold": int, "items": {id: qty}}
    confirmed: set = field(default_factory=set)       # pids que confirmaram

    def __post_init__(self) -> None:
        self.offer = {self.a: {"gold": 0, "items": {}},
                      self.b: {"gold": 0, "items": {}}}

    def partner(self, pid: int) -> int:
        return self.b if pid == self.a else self.a


class GameServer:
    def __init__(self, seed: int | None = None):
        self.state = GameState(seed=seed)
        self.conns: dict[int, Connection] = {}        # cid -> Connection
        self.invites: dict[int, int] = {}             # pid_alvo -> party_id pendente
        self.trade_req: dict[int, int] = {}           # pid_alvo -> pid_solicitante
        self.trades: dict[int, TradeSession] = {}     # pid -> sessão de troca ativa
        self._next_pid = 1

    # ================= envio / broadcast =================
    def send(self, pid: int, msg: dict) -> None:
        s = self.state.sessions.get(pid)
        if s and s.connected:
            s.conn.send(msg)

    def log(self, pid: int, text: str) -> None:
        self.send(pid, {"t": P.S_LOG, "text": text})

    def log_many(self, pids, text: str) -> None:
        for pid in pids:
            self.log(pid, text)

    def broadcast(self, msg: dict) -> None:
        for s in self.state.sessions.values():
            if s.connected:
                s.conn.send(msg)

    def send_panel(self, pid: int) -> None:
        s = self.state.sessions.get(pid)
        if s:
            self.send(pid, {"t": P.S_YOU, "player": s.player.to_panel()})

    def send_state(self, pid: int) -> None:
        s = self.state.sessions.get(pid)
        if not s:
            return
        self.send(pid, {
            "t": P.S_STATE,
            "view": self.state.view_for(pid),
            "players_online": self.state.online_names(),
            "daynight": self._daynight_label(),
            "hour": self.state.time_of_day,
            "weather": self.state.weather,
        })

    def send_combat(self, pid: int, enc: Encounter) -> None:
        self.send(pid, {"t": P.S_COMBAT, **enc.state_for(pid)})

    def _daynight_label(self) -> str:
        h = self.state.time_of_day
        if 6 <= h < 18:
            return "Dia"
        if h in (5, 18, 19):
            return "Crepúsculo"
        return "Noite"

    # ================= ciclo de vida da conexão =================
    async def on_connect(self, conn: Connection) -> None:
        self.conns[conn.cid] = conn

    async def on_disconnect(self, conn: Connection) -> None:
        self.conns.pop(conn.cid, None)
        if conn.pid is not None:
            s = self.state.sessions.get(conn.pid)
            if s:
                s.connected = False
                s.player.save()
                self._trade_cancel(conn.pid)           # cancela troca pendente, se houver
                self.trade_req.pop(conn.pid, None)
                self.broadcast({"t": P.S_CHAT, "from": "Sistema", "scope": "global",
                                "text": f"{s.player.name} desconectou."})

    # ================= dispatch =================
    async def on_message(self, conn: Connection, msg: dict) -> None:
        t = msg.get("t")
        if t == P.C_JOIN:
            await self._handle_join(conn, msg)
        elif conn.pid is None:
            conn.send({"t": P.S_ERROR, "text": "Envie 'join' primeiro."})
        elif t == P.C_MOVE:
            self._handle_move(conn.pid, msg.get("dir"))
        elif t == P.C_CHAT:
            self._handle_chat(conn.pid, msg.get("text", ""))
        elif t == P.C_COMBAT:
            self._handle_combat(conn.pid, msg.get("action"), msg.get("item"))
        elif t == P.C_ACTION:
            self._handle_action(conn.pid, msg.get("cmd"))
        elif t == P.C_VIEW:
            self._handle_view(conn.pid, msg)
        elif t == P.C_PING:
            conn.send({"t": P.C_PING})

    # ---- join (com reconexão por nome) ----
    async def _handle_join(self, conn: Connection, msg: dict) -> None:
        name = (msg.get("name") or "Herói").strip()[:16]
        klass = msg.get("cls", "Guerreiro")
        color = sanitize_color(msg.get("color"))

        # reconexão: se já existe sessão com esse nome, reusa o pid
        existing = next((s for s in self.state.sessions.values()
                         if s.player.name.lower() == name.lower()), None)
        if existing:
            existing.conn = conn
            existing.connected = True
            conn.pid = existing.pid
            self.conns[conn.cid] = conn
            self._send_full(existing.pid)
            self.broadcast({"t": P.S_CHAT, "from": "Sistema", "scope": "global",
                            "text": f"{name} reconectou."})
            return

        # carrega save ou cria novo personagem
        player = Player.load(name)
        if player is None:
            player = Player.create(name, klass, color)
            player.x, player.y = self.state.world.spawn
            offer(player, "wolf_hunt")  # missão inicial
        else:
            player.color = color  # permite trocar a cor de identificação ao relogar
        pid = self._next_pid
        self._next_pid += 1
        conn.pid = pid
        self.state.sessions[pid] = Session(pid=pid, player=player, conn=conn)

        conn.send({"t": P.S_WELCOME, "pid": pid, "player": player.to_panel()})
        self._send_full(pid)
        self.log(pid, f"Bem-vindo, {name} o {player.cls}! Use /help para comandos.")
        self.broadcast({"t": P.S_CHAT, "from": "Sistema", "scope": "global",
                        "text": f"{name} entrou na aventura!"})

    def _send_full(self, pid: int) -> None:
        self.send_panel(pid)
        self.send_state(pid)

    # ---- movimento ----
    def _handle_move(self, pid: int, direction: str) -> None:
        if self._in_combat(pid):
            self.log(pid, "⚔ Você está em combate! Termine a luta ou fuja.")
            return
        d = MOVES.get(direction)
        if not d:
            return
        s = self.state.sessions[pid]
        p = s.player
        nx, ny = p.x + d[0], p.y + d[1]
        if not self.state.world.in_bounds(nx, ny):
            return
        old_region = self.state.world.region_at(p.x, p.y)
        p.x, p.y = nx, ny
        new_region = self.state.world.region_at(nx, ny)
        if new_region != old_region:
            self.log(pid, f"🌍 Você entrou em: {new_region.capitalize()}")

        # encontro com inimigo?
        if (nx, ny) in self.state.world.enemies:
            self._start_encounter(pid, (nx, ny))

        self.send_state(pid)
        # atualiza quem estiver por perto (para ver o movimento)
        self._refresh_nearby(pid)

    def _handle_view(self, pid: int, msg: dict) -> None:
        """Ajusta o tamanho da janela do mapa ao painel do cliente (preenche tudo)."""
        s = self.state.sessions.get(pid)
        if not s:
            return
        cols = int(msg.get("cols", 25))
        rows = int(msg.get("rows", 13))
        hw = max(4, min(40, (cols - 1) // 2))
        hh = max(3, min(24, (rows - 1) // 2))
        if (hw, hh) != (s.view_hw, s.view_hh):
            s.view_hw, s.view_hh = hw, hh
            self.send_state(pid)

    def _refresh_nearby(self, pid: int) -> None:
        s = self.state.sessions[pid]
        for other in self.state.sessions.values():
            if other.pid != pid and other.connected:
                if abs(other.player.x - s.player.x) <= 20:
                    self.send_state(other.pid)

    # ---- combate ----
    def _in_combat(self, pid: int) -> bool:
        return any(pid in e.participants for e in self.state.encounters.values())

    def _start_encounter(self, pid: int, pos: tuple[int, int]) -> None:
        enc = self.state.encounters.get(pos)
        if enc is None:
            enc = Encounter(enemy=self.state.world.enemies[pos], pos=pos,
                            xp_mult=self.state.xp_mult)
            self.state.encounters[pos] = enc
        p = self.state.sessions[pid].player
        enc.add(pid, p)
        kind = "CHEFE" if enc.enemy.boss else "inimigo"
        self.log(pid, f"⚔ Você enfrenta o {kind} {enc.enemy.name}!")
        if enc.enemy.art:
            self.log(pid, enc.enemy.art)
        self.send_combat(pid, enc)

    def _handle_combat(self, pid: int, action: str, item: str | None) -> None:
        # localiza o encontro do jogador
        enc = next((e for e in self.state.encounters.values() if pid in e.participants), None)
        if enc is None:
            self.log(pid, "Você não está em combate.")
            return
        before = set(enc.participants.keys())
        logs = enc.act(pid, action, item)
        # destinatários dos logs incluem quem saiu nesta ação (fugitivo/derrotado)
        recipients = list(before | set(self._spectators(enc)))
        for line in logs:
            self.log_many(recipients, line)
        # atualiza painéis e estado de combate de quem continua na luta
        for ppid in list(enc.participants.keys()):
            self.send_panel(ppid)
            self.send_combat(ppid, enc)
        # quem fugiu (saiu vivo): fecha o painel de combate do cliente
        for ppid in before - set(enc.participants.keys()):
            s = self.state.sessions.get(ppid)
            if s and s.player.is_alive():
                self.send(ppid, {"t": P.S_COMBAT, "active": False})
                self.send_panel(ppid)
                self.send_state(ppid)

        self._check_deaths()

        if enc.finished:
            self._finish_encounter(enc)

    def _spectators(self, enc: Encounter) -> list[int]:
        # jogadores no mesmo tile que ainda não entraram (para ver os logs)
        return [s.pid for s in self.state.players_at(*enc.pos)
                if s.pid not in enc.participants]

    def _finish_encounter(self, enc: Encounter) -> None:
        # entrega recompensas individuais
        for ppid, plog in enc.rewards.items():
            for line in plog:
                self.log(ppid, line)
            self.send_panel(ppid)
        # remove inimigo derrotado do mundo
        if enc.victory and enc.pos in self.state.world.enemies:
            del self.state.world.enemies[enc.pos]
        # chefe de mundo derrotado: anúncio global e libera novo spawn
        if enc.victory and enc.enemy.world_boss:
            self.state.world_boss_pos = None
            self.broadcast({"t": P.S_CHAT, "from": "Sistema", "scope": "global",
                            "text": f"🎉 O Chefe de Mundo {enc.enemy.name} foi derrotado pelos heróis!"})
        self.state.encounters.pop(enc.pos, None)
        # encerra UI de combate e atualiza mapa
        for ppid in list(enc.participants.keys()) + list(enc.rewards.keys()):
            self.send(ppid, {"t": P.S_COMBAT, "active": False})
            self.send_state(ppid)
            s = self.state.sessions.get(ppid)
            if s:
                s.player.save()

    def _check_deaths(self) -> None:
        """Respawna jogadores derrotados na vila — com penalidade de ouro e XP."""
        for s in self.state.sessions.values():
            if s.connected and s.player.hp <= 0:
                p = s.player
                lost_gold = p.gold // 10
                lost_xp = p.xp // 10
                p.gold -= lost_gold
                p.xp -= lost_xp
                p.hp = max(1, p.max_hp // 2)
                p.mana = p.max_mana // 2
                p.x, p.y = self.state.world.spawn
                penalty = []
                if lost_gold:
                    penalty.append(f"{lost_gold} ouro")
                if lost_xp:
                    penalty.append(f"{lost_xp} XP")
                tail = f" Você perdeu {' e '.join(penalty)}." if penalty else ""
                self.log(s.pid, f"💀 Você caiu... e renasce na Vila.{tail}")
                self.send(s.pid, {"t": P.S_COMBAT, "active": False})
                self.send_panel(s.pid)
                self.send_state(s.pid)
                p.save()

    # ---- ações de mundo (NPC / descanso) ----
    def _handle_action(self, pid: int, cmd: str) -> None:
        s = self.state.sessions[pid]
        p = s.player
        region = self.state.world.region_at(p.x, p.y)
        if cmd == "rest":
            if REGIONS[region]["safe"]:
                p.hp, p.mana = p.max_hp, p.max_mana
                self.log(pid, "🛏 Você descansa na Vila. HP/Mana restaurados.")
                self.send_panel(pid)
            else:
                self.log(pid, "Só é possível descansar em zonas seguras (Vila).")
        elif cmd == "potion":
            # uso rápido de poção de vida fora de combate (tecla ou /use)
            ok, msg = p.use_consumable("health_potion")
            self.log(pid, msg)
            self.send_panel(pid)

    # ================= chat & comandos =================
    def _find_by_name(self, name: str) -> Session | None:
        return next((s for s in self.state.sessions.values()
                     if s.player.name.lower() == name.lower() and s.connected), None)

    def _handle_chat(self, pid: int, text: str) -> None:
        text = text.strip()
        if not text:
            return
        if not text.startswith("/"):
            s = self.state.sessions[pid]
            self.broadcast({"t": P.S_CHAT, "from": s.player.name,
                            "scope": "global", "text": text})
            return
        parts = text[1:].split(" ")
        cmd, args = parts[0].lower(), parts[1:]
        handler = getattr(self, f"_cmd_{cmd}", None)
        if handler:
            handler(pid, args)
        else:
            self.log(pid, f"Comando desconhecido: /{cmd} (use /help)")

    def _cmd_help(self, pid, args):
        self.log(pid,
            "Comandos: /help /who /msg <nome> <txt> /party [invite|accept] /roll [N] "
            "/emote <txt> /trade <nome> (depois: accept|gold|item|confirm|cancel) "
            "/quests /accept <id> /equip <id> /use <id> /rest /inventario "
            "/shop [buy|sell] /forge <id> /guild [create|join|leave|info|list] /ranking")

    def _cmd_who(self, pid, args):
        self.log(pid, "Online: " + ", ".join(self.state.online_names()))

    def _cmd_msg(self, pid, args):
        if len(args) < 2:
            self.log(pid, "Uso: /msg <nome> <mensagem>")
            return
        target = self._find_by_name(args[0])
        if not target:
            self.log(pid, "Jogador não encontrado/offline.")
            return
        sender = self.state.sessions[pid].player.name
        body = " ".join(args[1:])
        self.send(target.pid, {"t": P.S_CHAT, "from": f"(privado) {sender}",
                               "scope": "private", "text": body})
        self.send(pid, {"t": P.S_CHAT, "from": f"(para {target.player.name})",
                        "scope": "private", "text": body})

    def _cmd_w(self, pid, args):
        self._cmd_msg(pid, args)

    def _cmd_roll(self, pid, args):
        sides = int(args[0]) if args and args[0].isdigit() else 20
        result = random.randint(1, max(2, sides))
        name = self.state.sessions[pid].player.name
        self.broadcast({"t": P.S_CHAT, "from": "🎲", "scope": "global",
                        "text": f"{name} rolou d{sides} = {result}"})

    def _cmd_emote(self, pid, args):
        name = self.state.sessions[pid].player.name
        self.broadcast({"t": P.S_CHAT, "from": "*", "scope": "global",
                        "text": f"{name} {' '.join(args)}"})

    # ---- comércio entre jogadores ----
    def _cmd_trade(self, pid, args):
        sub = args[0].lower() if args else "status"
        if sub == "accept":
            self._trade_accept(pid)
        elif sub == "gold":
            self._trade_set_gold(pid, args[1:])
        elif sub == "item":
            self._trade_add_item(pid, args[1:])
        elif sub == "confirm":
            self._trade_confirm(pid)
        elif sub == "cancel":
            self._trade_cancel(pid, by_self=True)
        elif sub == "status":
            sess = self.trades.get(pid)
            if sess:
                self._trade_show(sess)
            else:
                self.log(pid, "Uso: /trade <nome> | accept | gold <n> | "
                              "item <id> [qtd] | confirm | cancel")
        else:
            self._trade_request(pid, args)

    def _trade_request(self, pid, args):
        target = self._find_by_name(args[0])
        if not target:
            self.log(pid, "Jogador não encontrado.")
            return
        if target.pid == pid:
            self.log(pid, "Você não pode comerciar consigo mesmo.")
            return
        if pid in self.trades or target.pid in self.trades:
            self.log(pid, "Um dos jogadores já está em uma troca.")
            return
        self.trade_req[target.pid] = pid
        sender = self.state.sessions[pid].player.name
        self.log(target.pid, f"💱 {sender} quer comerciar. Use /trade accept.")
        self.log(pid, f"Pedido de troca enviado a {target.player.name}.")

    def _trade_accept(self, pid):
        requester = self.trade_req.pop(pid, None)
        if requester is None or requester not in self.state.sessions:
            self.log(pid, "Nenhum pedido de troca pendente.")
            return
        if pid in self.trades or requester in self.trades:
            self.log(pid, "Um dos jogadores já está em uma troca.")
            return
        sess = TradeSession(a=requester, b=pid)
        self.trades[requester] = sess
        self.trades[pid] = sess
        self.log_many([requester, pid],
                      "💱 Troca iniciada. Comandos: /trade gold <n> | item <id> [qtd] | "
                      "confirm | cancel")
        self._trade_show(sess)

    def _trade_set_gold(self, pid, args):
        sess = self.trades.get(pid)
        if not sess:
            self.log(pid, "Você não está em uma troca.")
            return
        if not args or not args[0].isdigit():
            self.log(pid, "Uso: /trade gold <quantidade>")
            return
        amount = int(args[0])
        if amount > self.state.sessions[pid].player.gold:
            self.log(pid, "Você não tem ouro suficiente.")
            return
        sess.offer[pid]["gold"] = amount
        sess.confirmed.clear()
        self._trade_show(sess)

    def _trade_add_item(self, pid, args):
        sess = self.trades.get(pid)
        if not sess:
            self.log(pid, "Você não está em uma troca.")
            return
        if not args:
            self.log(pid, "Uso: /trade item <item_id> [qtd]")
            return
        item_id = args[0]
        qty = int(args[1]) if len(args) > 1 and args[1].isdigit() else 1
        p = self.state.sessions[pid].player
        if qty <= 0:
            sess.offer[pid]["items"].pop(item_id, None)   # qtd 0 remove da oferta
        elif p.inventory.get(item_id, 0) < qty:
            self.log(pid, f"Você não possui {qty}x {item_id}.")
            return
        else:
            sess.offer[pid]["items"][item_id] = qty
        sess.confirmed.clear()
        self._trade_show(sess)

    def _trade_confirm(self, pid):
        sess = self.trades.get(pid)
        if not sess:
            self.log(pid, "Você não está em uma troca.")
            return
        sess.confirmed.add(pid)
        if sess.confirmed >= {sess.a, sess.b}:
            self._trade_execute(sess)
        else:
            pname = self.state.sessions[pid].player.name
            self.log(sess.partner(pid), f"💱 {pname} confirmou. Use /trade confirm para fechar.")
            self.log(pid, "Você confirmou. Aguardando o outro jogador.")

    def _trade_execute(self, sess):
        pa = self.state.sessions[sess.a].player
        pb = self.state.sessions[sess.b].player
        oa, ob = sess.offer[sess.a], sess.offer[sess.b]
        # revalidação final (o estado pode ter mudado desde a confirmação)
        if (oa["gold"] > pa.gold or ob["gold"] > pb.gold
                or any(pa.inventory.get(i, 0) < q for i, q in oa["items"].items())
                or any(pb.inventory.get(i, 0) < q for i, q in ob["items"].items())):
            self.log_many([sess.a, sess.b], "💱 Troca falhou: ouro/itens insuficientes.")
            self._trade_cleanup(sess)
            return
        # transferência atômica de ouro
        pa.gold += ob["gold"] - oa["gold"]
        pb.gold += oa["gold"] - ob["gold"]
        # transferência de itens
        for i, q in oa["items"].items():
            pa.remove_item(i, q); pb.add_item(i, q)
        for i, q in ob["items"].items():
            pb.remove_item(i, q); pa.add_item(i, q)
        pa.save(); pb.save()
        self.log_many([sess.a, sess.b], "✅ Troca concluída!")
        self.send_panel(sess.a)
        self.send_panel(sess.b)
        self._trade_cleanup(sess)

    def _trade_cancel(self, pid, by_self=False):
        sess = self.trades.get(pid)
        if not sess:
            if by_self:
                self.log(pid, "Você não está em uma troca.")
            return
        self.log_many([sess.a, sess.b], "💱 Troca cancelada.")
        self._trade_cleanup(sess)

    def _trade_cleanup(self, sess):
        self.trades.pop(sess.a, None)
        self.trades.pop(sess.b, None)

    def _trade_show(self, sess):
        def fmt(o):
            items = ", ".join(f"{i} x{q}" for i, q in o["items"].items()) or "—"
            return f"{o['gold']} ouro | {items}"
        for pid in (sess.a, sess.b):
            partner = sess.partner(pid)
            pname = self.state.sessions[partner].player.name
            you = "✓" if pid in sess.confirmed else "…"
            them = "✓" if partner in sess.confirmed else "…"
            self.log(pid, f"💱 Sua oferta [{you}]: {fmt(sess.offer[pid])}")
            self.log(pid, f"💱 {pname} [{them}]: {fmt(sess.offer[partner])}")

    def _cmd_party(self, pid, args):
        if not args:  # cria grupo
            party_id = self.state.create_party(pid)
            self.log(pid, f"👥 Grupo #{party_id} criado. Use /party invite <nome>.")
            self.send_panel(pid)
            return
        sub = args[0].lower()
        if sub == "invite" and len(args) >= 2:
            target = self._find_by_name(args[1])
            s = self.state.sessions[pid]
            if not target:
                self.log(pid, "Jogador não encontrado.")
                return
            if not s.player.party:
                self.log(pid, "Crie um grupo primeiro com /party.")
                return
            self.invites[target.pid] = int(s.player.party)
            self.log(target.pid, f"👥 {s.player.name} convidou você. Use /party accept.")
            self.log(pid, f"Convite enviado a {target.player.name}.")
        elif sub == "accept":
            party_id = self.invites.pop(pid, None)
            party = self.state.parties.get(party_id) if party_id else None
            if not party:
                self.log(pid, "Nenhum convite pendente.")
                return
            party.members.add(pid)
            self.state.sessions[pid].player.party = str(party_id)
            for m in party.members:
                self.log(m, f"👥 {self.state.sessions[pid].player.name} entrou no grupo.")
            self.send_panel(pid)
        else:
            self.log(pid, "Uso: /party | /party invite <nome> | /party accept")

    def _cmd_quests(self, pid, args):
        p = self.state.sessions[pid].player
        if p.quests:
            self.log(pid, "— Missões ativas —")
            for qid, prog in p.quests.items():
                q = all_quests()[qid]
                self.log(pid, f"  {q['name']}: {prog}/{q['count']} — {q['desc']}")
        avail = [qid for qid in all_quests()
                 if qid not in p.quests and qid not in p.quests_done]
        if avail:
            self.log(pid, "— Disponíveis (/accept <id>) —")
            for qid in avail:
                self.log(pid, f"  [{qid}] {all_quests()[qid]['name']}")

    def _cmd_accept(self, pid, args):
        if not args:
            self.log(pid, "Uso: /accept <id>")
            return
        p = self.state.sessions[pid].player
        result = offer(p, args[0])
        self.log(pid, result or "Missão inválida ou já ativa/concluída.")
        self.send_panel(pid)

    def _cmd_equip(self, pid, args):
        if not args:
            self.log(pid, "Uso: /equip <item_id>")
            return
        p = self.state.sessions[pid].player
        if p.equip(args[0]):
            self.log(pid, f"🛡 Equipado: {item_name(args[0])}")
            self.send_panel(pid)
        else:
            self.log(pid, "Não foi possível equipar esse item.")

    def _cmd_use(self, pid, args):
        if not args:
            self.log(pid, "Uso: /use <item_id>")
            return
        p = self.state.sessions[pid].player
        ok, msg = p.use_consumable(args[0])
        self.log(pid, msg)
        self.send_panel(pid)

    def _cmd_rest(self, pid, args):
        self._handle_action(pid, "rest")

    # ---- guildas ----
    def _cmd_guild(self, pid, args):
        p = self.state.sessions[pid].player
        g = self.state.guilds
        usage = "Uso: /guild create <nome> | join <nome> | leave | info <nome> | list"
        if not args:
            self.log(pid, g.info(p.guild) if p.guild else usage)
            return
        sub = args[0].lower()
        if sub == "create" and len(args) >= 2:
            ok, msg = g.create(" ".join(args[1:])[:24], p.name)
            if ok:
                p.guild = g.find_player(p.name)
            self.log(pid, msg)
            self.send_panel(pid)
        elif sub == "join" and len(args) >= 2:
            ok, msg = g.add_member(" ".join(args[1:]), p.name)
            if ok:
                p.guild = g.find_player(p.name)
            self.log(pid, msg)
            self.send_panel(pid)
        elif sub == "leave":
            ok, msg = g.leave(p.name)
            if ok:
                p.guild = None
            self.log(pid, msg)
            self.send_panel(pid)
        elif sub == "info" and len(args) >= 2:
            self.log(pid, g.info(" ".join(args[1:])) or "Guilda inexistente.")
        elif sub == "list":
            names = g.list_names()
            self.log(pid, "🏰 Guildas: " + (", ".join(names) if names else "nenhuma ainda."))
        else:
            self.log(pid, usage)

    # ---- loja (apenas em zona segura) ----
    SELL_RATE = 0.5   # fração do valor base recebida ao vender

    def _cmd_shop(self, pid, args):
        p = self.state.sessions[pid].player
        region = self.state.world.region_at(p.x, p.y)
        if not REGIONS[region]["safe"]:
            self.log(pid, "🏪 Só há lojas em zonas seguras (Vila).")
            return
        sub = args[0].lower() if args else "list"
        if sub == "list":
            self._shop_list(pid)
        elif sub == "buy":
            self._shop_buy(pid, args[1:])
        elif sub == "sell":
            self._shop_sell(pid, args[1:])
        else:
            self.log(pid, "Uso: /shop | /shop buy <id> [qtd] | /shop sell <id> [qtd]")

    def _shop_list(self, pid):
        p = self.state.sessions[pid].player
        self.log(pid, f"🏪 — Loja da Vila — (seu ouro: {p.gold})")
        for iid in shop_catalog():
            it = get_item(iid)
            self.log(pid, f"  [{iid}] {it['name']} — {item_value(iid)} ouro ({it['rarity']})")
        self.log(pid, "Compre: /shop buy <id> [qtd] · Venda (50%): /shop sell <id> [qtd]")

    def _shop_buy(self, pid, args):
        if not args:
            self.log(pid, "Uso: /shop buy <item_id> [qtd]")
            return
        p = self.state.sessions[pid].player
        iid = args[0]
        qty = int(args[1]) if len(args) > 1 and args[1].isdigit() else 1
        if qty <= 0:
            self.log(pid, "Quantidade inválida.")
            return
        if iid not in shop_catalog():
            self.log(pid, "Item indisponível na loja (veja /shop).")
            return
        cost = item_value(iid) * qty
        if p.gold < cost:
            self.log(pid, f"Ouro insuficiente: custa {cost}, você tem {p.gold}.")
            return
        p.gold -= cost
        p.add_item(iid, qty)
        p.save()
        self.log(pid, f"🛒 Comprou {qty}x {item_name(iid)} por {cost} ouro.")
        self.send_panel(pid)

    def _shop_sell(self, pid, args):
        if not args:
            self.log(pid, "Uso: /shop sell <item_id> [qtd]")
            return
        p = self.state.sessions[pid].player
        iid = args[0]
        qty = int(args[1]) if len(args) > 1 and args[1].isdigit() else 1
        if qty <= 0:
            self.log(pid, "Quantidade inválida.")
            return
        if not get_item(iid):
            self.log(pid, "Item desconhecido.")
            return
        if p.inventory.get(iid, 0) < qty:
            self.log(pid, f"Você não possui {qty}x {iid}.")
            return
        gain = max(1, int(item_value(iid) * self.SELL_RATE)) * qty
        p.remove_item(iid, qty)
        p.gold += gain
        p.save()
        self.log(pid, f"💰 Vendeu {qty}x {item_name(iid)} por {gain} ouro.")
        self.send_panel(pid)

    # ---- forja (apenas em zona segura) ----
    def _forge_cost(self, iid: str, lvl: int) -> int:
        return int(item_value(iid) * 0.5 * (lvl + 1)) + 20

    def _cmd_forge(self, pid, args):
        p = self.state.sessions[pid].player
        if not REGIONS[self.state.world.region_at(p.x, p.y)]["safe"]:
            self.log(pid, "⚒ Só é possível forjar em zonas seguras (Vila).")
            return
        if not args:
            self.log(pid, "⚒ Forja (consome ouro + 1 Essência Monstruosa). /forge <item_id>:")
            forjaveis = {**{iid: 0 for iid in p.equipment.values()},
                         **{iid: 0 for iid in p.inventory if is_equippable(iid)}}
            if not forjaveis:
                self.log(pid, "  (nenhum equipamento para forjar)")
            for iid in forjaveis:
                lvl = p.upgrades.get(iid, 0)
                cap = "MÁX" if lvl >= Player.FORGE_MAX else f"{self._forge_cost(iid, lvl)} ouro"
                self.log(pid, f"  {iid} +{lvl} → {cap}")
            return
        iid = args[0]
        if not is_equippable(iid):
            self.log(pid, "Só equipamentos podem ser forjados.")
            return
        if iid not in p.equipment.values() and p.inventory.get(iid, 0) <= 0:
            self.log(pid, "Você não possui esse equipamento.")
            return
        lvl = p.upgrades.get(iid, 0)
        if lvl >= Player.FORGE_MAX:
            self.log(pid, f"{item_name(iid)} já está no nível máximo (+{Player.FORGE_MAX}).")
            return
        cost = self._forge_cost(iid, lvl)
        if p.gold < cost:
            self.log(pid, f"Ouro insuficiente: a forja custa {cost}.")
            return
        if p.inventory.get("monster_essence", 0) < 1:
            self.log(pid, "Falta 1 Essência Monstruosa (cai de elites e chefes).")
            return
        p.gold -= cost
        p.remove_item("monster_essence")
        p.upgrades[iid] = lvl + 1
        p.refresh_maxes()
        p.save()
        self.log(pid, f"⚒ Forjado! {item_name(iid)} agora é +{lvl + 1}.")
        self.send_panel(pid)

    # ---- ranking ----
    def _cmd_ranking(self, pid, args):
        live = {s.player.name.lower(): {
                    "name": s.player.name, "cls": s.player.cls,
                    "level": s.player.level, "xp": s.player.xp, "gold": s.player.gold}
                for s in self.state.sessions.values() if s.connected}
        self.log(pid, "🏆 — Ranking (top 10) —")
        for i, e in enumerate(leaderboard(live), 1):
            self.log(pid, f"  {i}. {e['name']} — {e['cls']} Nv {e['level']} ({e['xp']} XP)")

    def _cmd_rank(self, pid, args):
        self._cmd_ranking(pid, args)

    # ================= eventos globais =================
    def _tick_xp_event(self) -> None:
        """Bênção de XP global: a cada tick, chance de iniciar/encerrar XP em dobro."""
        if self.state.xp_event_ticks > 0:
            self.state.xp_event_ticks -= 1
            if self.state.xp_event_ticks == 0:
                self.state.xp_mult = 1.0
                self.broadcast({"t": P.S_CHAT, "from": "Sistema", "scope": "global",
                                "text": "✨ A Bênção de XP terminou."})
        elif random.random() < 0.05:
            self.state.xp_mult = 2.0
            self.state.xp_event_ticks = 6  # ~30s de XP em dobro
            self.broadcast({"t": P.S_CHAT, "from": "Sistema", "scope": "global",
                            "text": "✨ Bênção de XP! XP em DOBRO por tempo limitado!"})

    # ================= tick do mundo =================
    def _move_enemies(self) -> None:
        """Inimigos vagueiam aleatoriamente; se um pisar num jogador, inicia combate.
        Inimigos em combate ativo não se movem (posições puladas)."""
        moves = self.state.world.wander_enemies(skip=set(self.state.encounters.keys()))
        for _old, new, _enemy in moves:
            for s in self.state.players_at(*new):
                if not self._in_combat(s.pid):
                    self._start_encounter(s.pid, new)

    def _maybe_spawn_world_boss(self) -> None:
        """Chance periódica de nascer um Chefe de Mundo que escala com os jogadores online."""
        st = self.state
        if st.world_boss_pos is not None:
            return                                   # só um por vez
        online = len(st.online_names())
        if online == 0 or random.random() >= 0.04:
            return
        pos = st.world.random_unsafe_tile()
        if pos is None:
            return
        from game.enemy import Enemy, bestiary
        bosses = [eid for eid, e in bestiary().items() if e.get("boss")]
        boss = Enemy.spawn(random.choice(bosses), level=7)
        scale = 1 + 0.6 * online                     # mais jogadores -> mais forte
        boss.hp = int(boss.hp * scale)
        boss.max_hp = boss.hp
        boss.atk = int(boss.atk * 1.3)
        boss.xp = int(boss.xp * 2)
        boss.gold = int(boss.gold * 2)
        boss.world_boss = True
        boss.name = f"{boss.name} (Chefe de Mundo)"
        st.world.enemies[pos] = boss
        st.world_boss_pos = pos
        region = st.world.region_at(*pos)
        self.broadcast({"t": P.S_CHAT, "from": "Sistema", "scope": "global",
                        "text": f"🔥 Um CHEFE DE MUNDO surgiu em {region.capitalize()}! "
                                "Reúnam-se e derrotem-no!"})

    async def world_tick(self) -> None:
        """Avança tempo, clima, respawns e autosave a cada 5s."""
        while True:
            await asyncio.sleep(5)
            self.state.time_of_day = (self.state.time_of_day + 1) % 24
            if random.random() < 0.2:
                self.state.weather = random.choice(WEATHERS)
            if random.random() < 0.5:
                self.state.world.respawn_enemy()
            self._tick_xp_event()
            self._move_enemies()
            self._maybe_spawn_world_boss()
            # autosave + atualização de relógio/clima para todos
            for s in self.state.sessions.values():
                if s.connected:
                    s.player.save()
                    self.send_state(s.pid)

    async def run(self, host: str, port: int) -> None:
        server = await serve(host, port, self.on_connect, self.on_message, self.on_disconnect)
        asyncio.create_task(self.world_tick())
        addr = ", ".join(str(s.getsockname()) for s in server.sockets)
        print(f"🗺  Servidor RPG ouvindo em {addr}")
        print("   Jogadores entram com: python -m client.app  (host = seu IP da LAN)")
        async with server:
            await server.serve_forever()


def main() -> None:
    host = sys.argv[1] if len(sys.argv) > 1 else "0.0.0.0"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 7777
    try:
        asyncio.run(GameServer().run(host, port))
    except KeyboardInterrupt:
        print("\nServidor encerrado.")


if __name__ == "__main__":
    main()
