"""
Mundo gerado proceduralmente.

Abordagem: distribuímos "sementes" de região aleatoriamente no grid e atribuímos
cada tile à região da semente mais próxima (diagrama de Voronoi). Isso cria
fronteiras orgânicas entre Floresta, Caverna, Vila, Castelo, Deserto e Ruínas.

Inimigos são espalhados conforme a região de cada tile. A Vila é zona segura
(sem inimigos) e ponto de spawn dos jogadores.
"""
from __future__ import annotations

import random

from .enemy import bosses_for_region, enemies_for_region

REGIONS = {
    "floresta": {"tile": "♣", "color": "green",        "safe": False},
    "caverna":  {"tile": "▲", "color": "grey50",       "safe": False},
    "vila":     {"tile": "⌂", "color": "bright_yellow", "safe": True},
    "castelo":  {"tile": "♜", "color": "red",          "safe": False},
    "deserto":  {"tile": "~", "color": "yellow",       "safe": False},
    "ruinas":   {"tile": "†", "color": "magenta",      "safe": False},
}


class World:
    """Mapa autoritativo do servidor: terreno + inimigos posicionados."""

    def __init__(self, width: int = 60, height: int = 24, seed: int | None = None):
        self.width = width
        self.height = height
        self.rng = random.Random(seed)
        self.grid: list[list[str]] = []          # região por tile
        self.enemies: dict[tuple[int, int], object] = {}  # (x,y) -> Enemy
        self.spawn: tuple[int, int] = (width // 2, height // 2)
        self._generate()

    # ---- geração ----
    def _generate(self) -> None:
        names = list(REGIONS.keys())
        # uma semente por região + algumas extras para variedade
        seeds: list[tuple[int, int, str]] = []
        for name in names:
            sx, sy = self.rng.randrange(self.width), self.rng.randrange(self.height)
            seeds.append((sx, sy, name))
        for _ in range(6):
            sx, sy = self.rng.randrange(self.width), self.rng.randrange(self.height)
            seeds.append((sx, sy, self.rng.choice(names)))

        # Voronoi: cada tile recebe a região da semente mais próxima
        self.grid = [[""] * self.width for _ in range(self.height)]
        for y in range(self.height):
            for x in range(self.width):
                best, region = 1e9, "floresta"
                for sx, sy, name in seeds:
                    d = (sx - x) ** 2 + (sy - y) ** 2
                    if d < best:
                        best, region = d, name
                self.grid[y][x] = region

        # garante uma vila central segura como ponto de spawn
        cx, cy = self.width // 2, self.height // 2
        for y in range(cy - 1, cy + 2):
            for x in range(cx - 2, cx + 3):
                if 0 <= x < self.width and 0 <= y < self.height:
                    self.grid[y][x] = "vila"
        self.spawn = (cx, cy)
        self._populate()

    def _populate(self) -> None:
        from .enemy import Enemy
        density = 0.06
        for y in range(self.height):
            for x in range(self.width):
                region = self.grid[y][x]
                if REGIONS[region]["safe"]:
                    continue
                if self.rng.random() < density:
                    pool = enemies_for_region(region)
                    if pool:
                        self.enemies[(x, y)] = Enemy.spawn(self.rng.choice(pool))
        # posiciona um chefe por região não-segura
        placed = set()
        for region in REGIONS:
            if REGIONS[region]["safe"]:
                continue
            bosses = bosses_for_region(region)
            if not bosses:
                continue
            tiles = [(x, y) for y in range(self.height) for x in range(self.width)
                     if self.grid[y][x] == region and (x, y) not in self.enemies]
            if tiles:
                pos = self.rng.choice(tiles)
                self.enemies[pos] = Enemy.spawn(self.rng.choice(bosses))
                placed.add(pos)

    # ---- consultas ----
    def region_at(self, x: int, y: int) -> str:
        return self.grid[y][x]

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def respawn_enemy(self) -> None:
        """Repõe um inimigo aleatório no mapa (chamado periodicamente)."""
        from .enemy import Enemy
        x, y = self.rng.randrange(self.width), self.rng.randrange(self.height)
        region = self.grid[y][x]
        if REGIONS[region]["safe"] or (x, y) in self.enemies:
            return
        pool = enemies_for_region(region)
        if pool:
            self.enemies[(x, y)] = Enemy.spawn(self.rng.choice(pool))
