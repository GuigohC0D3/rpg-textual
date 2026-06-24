"""
Widgets de UI do cliente (Textual + Rich).

  Sidebar     -> painel lateral com ficha do personagem
  MapView     -> área principal com o mapa e ocupantes
  CombatPanel -> arte ASCII do inimigo + barra de HP durante a luta
"""
from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from common import protocol as P
from game.items import describe, item_name

# Linhas do painel do mapa gastas com cabeçalho (info + branco) e rodapé (legenda).
MAP_HEADER_LINES = 2
MAP_FOOTER_LINES = 1

RARITY_STYLE = {"comum": "white", "raro": "cyan", "epico": "magenta", "lendario": "yellow"}


def _bar(cur: int, mx: int, width: int, color: str) -> Text:
    """Barra de progresso textual (HP/Mana/XP)."""
    mx = max(1, mx)
    filled = int(width * max(0, min(cur, mx)) / mx)
    t = Text()
    t.append("█" * filled, style=color)
    t.append("░" * (width - filled), style="grey37")
    t.append(f" {cur}/{mx}", style="white")
    return t


class Sidebar(Static):
    """Ficha do personagem: classe, HP, Mana, nível, XP, ouro, equip., inventário."""

    def update_panel(self, p: dict) -> None:
        t = Text()
        t.append(f"{p['name']}\n", style=f"bold {p.get('color', 'bright_white')}")
        t.append(f"{p['cls']} • Nível {p['level']}\n\n", style="bright_yellow")

        t.append("HP   ", style="bold"); t.append(_bar(p["hp"], p["max_hp"], 12, "red")); t.append("\n")
        t.append("MP   ", style="bold"); t.append(_bar(p["mana"], p["max_mana"], 12, "blue")); t.append("\n")
        t.append("XP   ", style="bold"); t.append(_bar(p["xp"], p["xp_next"], 12, "green")); t.append("\n\n")

        t.append(f"ATK {p['atk']}   DEF {p['def']}   Crit {int(p['crit']*100)}%\n", style="white")
        t.append(f"Ouro: {p['gold']}\n", style="bright_yellow")
        t.append(f"Habilidade: {p['skill']}\n", style="cyan")
        if p.get("party"):
            t.append(f"Grupo: #{p['party']}\n", style="green")

        t.append("\nEquipamento:\n", style="bold underline")
        if p["equipment"]:
            upgrades = p.get("upgrades", {})
            for slot, iid in p["equipment"].items():
                t.append(f" {slot}: ", style="grey70")
                up = upgrades.get(iid, 0)
                suffix = f" +{up}" if up else ""
                t.append(f"{item_name(iid)}{suffix}\n",
                         style=RARITY_STYLE.get(_rarity(iid), "white"))
        else:
            t.append(" (nada)\n", style="grey50")

        t.append("\nInventário (/use|/equip <id>):\n", style="bold underline")
        if p["inventory"]:
            for iid, qty in p["inventory"].items():
                t.append(f" {iid} x{qty}\n", style=RARITY_STYLE.get(_rarity(iid), "white"))
        else:
            t.append(" (vazio)\n", style="grey50")

        if p.get("quests"):
            t.append("\nMissões:\n", style="bold underline")
            for qid, prog in p["quests"].items():
                t.append(f" {qid}: {prog}\n", style="grey70")

        self.update(t)


def _rarity(item_id: str) -> str:
    from game.items import get_item
    it = get_item(item_id)
    return it["rarity"] if it else "comum"


class MapView(Static):
    """Renderiza a janela do mundo ao redor do jogador, com cores por região.

    A janela é dimensionada para preencher todo o painel: o widget informa ao
    servidor quantos tiles cabem (cols/rows) e recebe o recorte exato do mundo.
    """

    def on_resize(self, event) -> None:
        self.send_viewport()

    def send_viewport(self) -> None:
        """Informa ao servidor o tamanho do mapa (em tiles) que cabe no painel."""
        cs = self.content_size
        if cs.width <= 0 or cs.height <= 0:
            return
        cols = max(8, cs.width // 2)                                   # 2 colunas por tile
        rows = max(6, cs.height - MAP_HEADER_LINES - MAP_FOOTER_LINES)
        screen = self.screen
        if hasattr(screen, "send_msg"):
            screen.send_msg({"t": P.C_VIEW, "cols": cols, "rows": rows})

    def update_view(self, view: dict, daynight: str, weather: str, hour: int) -> None:
        t = Text()
        t.append(f"📍 {view['region'].capitalize()}  ", style="bold bright_yellow")
        t.append(f"🕐 {hour:02d}h {daynight}  ", style="cyan")
        t.append(f"☁ {weather}\n\n", style="grey70")
        for row in view["rows"]:
            for cell in row:
                t.append(cell["ch"], style=cell["color"])
                t.append(" ")
            t.append("\n")
        t.append("@ você  P outro  e inimigo  & CHEFE  •  "
                 "WASD mover · Enter chat · 1-6 combate", style="grey50")
        self.update(t)


class CombatPanel(Static):
    """Mostra o inimigo atual, sua arte ASCII e a barra de HP."""

    def show(self, c: dict) -> None:
        t = Text()
        if not c.get("active"):
            t.append("Sem combate.\n", style="grey50")
            t.append("Caminhe até um inimigo (e/&) para lutar.", style="grey50")
            self.update(t)
            return
        title = "👑 CHEFE" if c.get("boss") else "⚔ Combate"
        t.append(f"{title}: {c['enemy']}\n", style="bold red")
        if c.get("art"):
            t.append(c["art"] + "\n", style="bright_red")
        t.append(_bar(c["enemy_hp"], c["enemy_max_hp"], 16, "red"))
        if c.get("enemy_status"):
            t.append("\n☠ Inimigo: " + ", ".join(c["enemy_status"]), style="magenta")
        if c.get("my_status"):
            t.append("\n✦ Você: " + ", ".join(c["my_status"]), style="green")
        t.append("\nAliados: " + ", ".join(c.get("allies", [])) + "\n", style="cyan")
        ult = c.get("ult_name", "Suprema")
        ult_cd = c.get("ult_cd", 0)
        ult_label = f"[6]{ult} (recarga {ult_cd})" if ult_cd else f"[6]{ult}"
        t.append("\n[1]Atacar [2]Defender [3]Habilidade\n[4]Poção [5]Fugir  ", style="bright_white")
        t.append(ult_label, style="yellow" if not ult_cd else "grey50")
        self.update(t)
