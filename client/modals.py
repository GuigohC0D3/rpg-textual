"""
Modais interativos do cliente: Loja e Inventário.

São construídos a partir do último painel do jogador (ficha recebida via S_YOU)
e do catálogo local em game.items. As ações (comprar/vender/equipar/usar) são
roteadas como comandos ao servidor autoritativo; quando o servidor responde com
um novo painel (S_YOU), a GameScreen chama refresh_data() para reabastecer a UI.
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from common import protocol as P
from game.items import (EQUIP_SLOTS, compare_to_equipped, get_item, is_equippable,
                        item_name, item_value, stat_summary)

SELL_RATE = 0.5

# Ordem de organização do inventário: por categoria e depois por raridade.
_CAT_ORDER = {**{s: i for i, s in enumerate(EQUIP_SLOTS)}, "consumable": 90, "material": 99}
_RARITY_ORDER = {"lendario": 0, "epico": 1, "raro": 2, "comum": 3}


def _sort_key(iid: str):
    it = get_item(iid) or {}
    return (_CAT_ORDER.get(it.get("slot"), 50),
            _RARITY_ORDER.get(it.get("rarity"), 5),
            it.get("name", iid))


class _BaseModal(ModalScreen):
    """Base comum: caixa centralizada, rodapé de dica e linha de status."""

    BINDINGS = [("escape", "close", "Fechar")]
    CSS = """
    _BaseModal { align: center middle; }
    #box { width: 78; height: 30; border: round cyan; background: $surface; padding: 1 2; }
    #title { text-style: bold; color: cyan; }
    .col-title { text-style: bold underline; }
    OptionList { height: 1fr; border: round $primary 30%; }
    #note { color: $warning; height: 1; }
    .hint { color: $text-muted; }
    """

    def __init__(self, host) -> None:
        super().__init__()
        self.host = host                # GameScreen (tem send_msg)
        self.panel: dict = host.last_panel or {}

    def action_close(self) -> None:
        self.dismiss()

    def note(self, text: str) -> None:
        try:
            self.query_one("#note", Static).update(text)
        except Exception:
            pass


class ShopModal(_BaseModal):
    """Loja: comprar (catálogo) à esquerda, vender (inventário) à direita."""

    def __init__(self, host) -> None:
        super().__init__(host)
        self._region = getattr(host, "last_region", "") or ""

    def compose(self) -> ComposeResult:
        with Vertical(id="box"):
            yield Static(id="title")
            with Horizontal():
                with Vertical():
                    yield Static("Comprar", classes="col-title")
                    yield OptionList(id="buy")
                with Vertical():
                    yield Static("Vender (50%)", classes="col-title")
                    yield OptionList(id="sell")
            yield Static("", id="note")
            yield Static("↑↓ navegar · Enter comprar/vender · Esc fechar", classes="hint")

    def on_mount(self) -> None:
        self.refresh_data(self.panel)
        self.query_one("#buy", OptionList).focus()

    def refresh_data(self, panel: dict) -> None:
        self.panel = panel or {}
        gold = self.panel.get("gold", 0)
        warn = "" if self._region == "vila" else "  (entre na Vila para negociar)"
        self.query_one("#title", Static).update(f"🏪 Loja da Vila — Ouro: {gold}{warn}")

        from game.items import shop_catalog
        buy = self.query_one("#buy", OptionList)
        buy.clear_options()
        for iid in shop_catalog():
            it = get_item(iid)
            stats = stat_summary(iid)
            label = f"{it['name']} ({stats}) — {item_value(iid)} ouro" if stats \
                else f"{it['name']} — {item_value(iid)} ouro"
            buy.add_option(Option(label, id=f"buy:{iid}"))

        sell = self.query_one("#sell", OptionList)
        sell.clear_options()
        inv = self.panel.get("inventory", {})
        if not inv:
            sell.add_option(Option("(inventário vazio)", id=None))
        for iid in sorted(inv, key=_sort_key):
            it = get_item(iid)
            if not it:
                continue
            price = max(1, int(item_value(iid) * SELL_RATE))
            sell.add_option(Option(f"{it['name']} x{inv[iid]} — {price} ouro", id=f"sell:{iid}"))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        oid = event.option.id
        if not oid:
            return
        action, iid = oid.split(":", 1)
        verb = "buy" if action == "buy" else "sell"
        self.host.send_msg({"t": P.C_CHAT, "text": f"/shop {verb} {iid}"})


class InventoryModal(_BaseModal):
    """Inventário: equipamento atual + itens organizados, equipáveis/usáveis."""

    def compose(self) -> ComposeResult:
        with Vertical(id="box"):
            yield Static(id="title")
            yield Static(id="equipped")
            yield Static("Itens (organizados por categoria/raridade):", classes="col-title")
            yield OptionList(id="items")
            yield Static("", id="note")
            yield Static("↑↓ navegar · Enter equipar/usar · Esc fechar", classes="hint")

    def on_mount(self) -> None:
        self.refresh_data(self.panel)
        self.query_one("#items", OptionList).focus()

    def refresh_data(self, panel: dict) -> None:
        self.panel = panel or {}
        self.query_one("#title", Static).update(
            f"🎒 Inventário de {self.panel.get('name', '?')} — Ouro: {self.panel.get('gold', 0)}")

        upgrades = self.panel.get("upgrades", {})
        equip = self.panel.get("equipment", {})
        if equip:
            parts = []
            for slot, iid in equip.items():
                up = upgrades.get(iid, 0)
                parts.append(f"{slot}: {item_name(iid)}" + (f" +{up}" if up else ""))
            equipped = "Equipado — " + "  |  ".join(parts)
        else:
            equipped = "Equipado — (nada)"
        self.query_one("#equipped", Static).update(equipped)

        items = self.query_one("#items", OptionList)
        items.clear_options()
        inv = self.panel.get("inventory", {})
        if not inv:
            items.add_option(Option("(vazio)", id=None))
        for iid in sorted(inv, key=_sort_key):
            it = get_item(iid)
            if not it:
                items.add_option(Option(f"{iid} x{inv[iid]}", id=None))
                continue
            qty = inv[iid]
            stats = stat_summary(iid)
            info = f"  ({stats})" if stats else ""
            if is_equippable(iid):
                up = upgrades.get(iid, 0)
                tag, oid = "[equipar]", f"equip:{iid}"
                extra = f" +{up}" if up else ""
                info += compare_to_equipped(iid, equip)
            elif it.get("slot") == "consumable":
                tag, oid, extra = "[usar]", f"use:{iid}", ""
            else:
                tag, oid, extra = "[material]", None, ""
            items.add_option(Option(f"{it['name']}{extra} x{qty}{info}  {tag}", id=oid))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        oid = event.option.id
        if not oid:
            return
        action, iid = oid.split(":", 1)
        cmd = "/equip" if action == "equip" else "/use"
        self.host.send_msg({"t": P.C_CHAT, "text": f"{cmd} {iid}"})
