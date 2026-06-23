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

from common import protocol as P
from game.combat import Encounter
from game.items import describe, get_item, item_name
from game.map import REGIONS
from game.player import Player
from game.quests import all_quests, offer

from .network import Connection, serve
from .world import WEATHERS, GameState, Session

MOVES = {"n": (0, -1), "s": (0, 1), "e": (1, 0), "w": (-1, 0)}


class GameServer:
    def __init__(self, seed: int | None = None):
        self.state = GameState(seed=seed)
        self.conns: dict[int, Connection] = {}        # cid -> Connection
        self.invites: dict[int, int] = {}             # pid_alvo -> party_id pendente
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
        elif t == P.C_PING:
            conn.send({"t": P.C_PING})

    # ---- join (com reconexão por nome) ----
    async def _handle_join(self, conn: Connection, msg: dict) -> None:
        name = (msg.get("name") or "Herói").strip()[:16]
        klass = msg.get("cls", "Guerreiro")

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
            player = Player.create(name, klass)
            player.x, player.y = self.state.world.spawn
            offer(player, "wolf_hunt")  # missão inicial
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
            enc = Encounter(enemy=self.state.world.enemies[pos], pos=pos)
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
        logs = enc.act(pid, action, item)
        for line in logs:
            self.log_many(list(enc.participants.keys()) + self._spectators(enc), line)
        # atualiza painéis e estado de combate dos participantes
        for ppid in list(enc.participants.keys()):
            self.send_panel(ppid)
            self.send_combat(ppid, enc)

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
        self.state.encounters.pop(enc.pos, None)
        # encerra UI de combate e atualiza mapa
        for ppid in list(enc.participants.keys()) + list(enc.rewards.keys()):
            self.send(ppid, {"t": P.S_COMBAT, "active": False})
            self.send_state(ppid)
            s = self.state.sessions.get(ppid)
            if s:
                s.player.save()

    def _check_deaths(self) -> None:
        """Respawna jogadores derrotados na vila com metade do HP."""
        for s in self.state.sessions.values():
            if s.connected and s.player.hp <= 0:
                s.player.hp = max(1, s.player.max_hp // 2)
                s.player.mana = s.player.max_mana // 2
                s.player.x, s.player.y = self.state.world.spawn
                self.log(s.pid, "💀 Você caiu... e renasce na Vila.")
                self.send(s.pid, {"t": P.S_COMBAT, "active": False})
                self.send_panel(s.pid)
                self.send_state(s.pid)
                s.player.save()

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
            "/emote <txt> /trade <nome> /quests /accept <id> /equip <id> /use <id> /rest")

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

    def _cmd_trade(self, pid, args):
        if not args:
            self.log(pid, "Uso: /trade <nome>")
            return
        target = self._find_by_name(args[0])
        if not target:
            self.log(pid, "Jogador não encontrado.")
            return
        sender = self.state.sessions[pid].player.name
        self.log(target.pid, f"💱 {sender} quer comerciar (recurso em desenvolvimento).")
        self.log(pid, f"Pedido de troca enviado a {target.player.name}.")

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

    # ================= tick do mundo =================
    async def world_tick(self) -> None:
        """Avança tempo, clima, respawns e autosave a cada 5s."""
        while True:
            await asyncio.sleep(5)
            self.state.time_of_day = (self.state.time_of_day + 1) % 24
            if random.random() < 0.2:
                self.state.weather = random.choice(WEATHERS)
            if random.random() < 0.5:
                self.state.world.respawn_enemy()
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
