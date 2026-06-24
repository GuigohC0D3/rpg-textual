"""
Mundo gerado proceduralmente com ruído de Perlin.

Abordagem (estilo Whittaker): dois campos de ruído de Perlin contínuos —
ELEVAÇÃO e UMIDADE — são gerados com fBm (soma de oitavas) e normalizados.
Cada tile é classificado num bioma conforme (elevação, umidade), produzindo
biomas orgânicos e contíguos. A Vila central é forçada como zona segura e
ponto de spawn. O Perlin é implementado em Python puro (sem dependências).

Inimigos são espalhados conforme a região de cada tile.
"""
from __future__ import annotations

import math
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


class _PerlinNoise:
    """Ruído gradiente de Perlin 2D (improved noise) com tabela de permutação.

    `noise(x, y)` devolve um valor suave em ~[-1, 1]; pontos próximos têm
    valores próximos (continuidade), o que gera terreno orgânico."""

    def __init__(self, seed: int = 0):
        p = list(range(256))
        random.Random(seed).shuffle(p)
        self.perm = p + p          # duplica p/ evitar overflow de índice

    @staticmethod
    def _fade(t: float) -> float:
        return t * t * t * (t * (t * 6 - 15) + 10)

    @staticmethod
    def _lerp(a: float, b: float, t: float) -> float:
        return a + t * (b - a)

    @staticmethod
    def _grad(h: int, x: float, y: float) -> float:
        h &= 7                     # 8 direções de gradiente
        u = x if h < 4 else y
        v = y if h < 4 else x
        return (u if h & 1 == 0 else -u) + (v if h & 2 == 0 else -v)

    def noise(self, x: float, y: float) -> float:
        xi, yi = math.floor(x), math.floor(y)
        X, Y = xi & 255, yi & 255
        xf, yf = x - xi, y - yi
        u, v = self._fade(xf), self._fade(yf)
        p = self.perm
        aa = p[p[X] + Y]
        ab = p[p[X] + Y + 1]
        ba = p[p[X + 1] + Y]
        bb = p[p[X + 1] + Y + 1]
        x1 = self._lerp(self._grad(aa, xf, yf), self._grad(ba, xf - 1, yf), u)
        x2 = self._lerp(self._grad(ab, xf, yf - 1), self._grad(bb, xf - 1, yf - 1), u)
        return self._lerp(x1, x2, v)


def _fbm(noise: _PerlinNoise, x: float, y: float,
         octaves: int = 4, lacunarity: float = 2.0, gain: float = 0.5) -> float:
    """Fractal Brownian Motion: soma oitavas de ruído (detalhe multiescala)."""
    amp, freq, total, norm = 1.0, 1.0, 0.0, 0.0
    for _ in range(octaves):
        total += amp * noise.noise(x * freq, y * freq)
        norm += amp
        amp *= gain
        freq *= lacunarity
    return total / norm if norm else 0.0


def _normalize(grid: list[list[float]]) -> None:
    """Reescala um campo 2D para [0, 1] in-place (garante a faixa cheia de biomas)."""
    flat = [v for row in grid for v in row]
    lo, hi = min(flat), max(flat)
    span = hi - lo or 1.0
    for row in grid:
        for i, v in enumerate(row):
            row[i] = (v - lo) / span


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

    # ---- geração (Perlin: elevação + umidade) ----
    # Escalas de amostragem: menor = biomas maiores/mais suaves.
    ELEV_SCALE = 0.11
    MOIST_SCALE = 0.09

    @staticmethod
    def _biome(elev: float, moist: float) -> str:
        """Classifica um tile em bioma a partir de elevação e umidade (0..1)."""
        if elev < 0.30:
            return "caverna"        # terras baixas / subterrâneo
        if elev >= 0.70:
            return "castelo"        # terras altas / fortalezas
        if moist < 0.40:
            return "deserto"        # planície seca
        if moist >= 0.62:
            return "floresta"       # planície úmida
        return "ruinas"             # umidade intermediária

    def _generate(self) -> None:
        elev_noise = _PerlinNoise(self.rng.randrange(1 << 30))
        moist_noise = _PerlinNoise(self.rng.randrange(1 << 30))

        elev = [[_fbm(elev_noise, x * self.ELEV_SCALE, y * self.ELEV_SCALE)
                 for x in range(self.width)] for y in range(self.height)]
        # offset desloca a amostragem p/ a umidade não copiar a elevação
        moist = [[_fbm(moist_noise, x * self.MOIST_SCALE + 50, y * self.MOIST_SCALE + 50)
                  for x in range(self.width)] for y in range(self.height)]
        _normalize(elev)
        _normalize(moist)

        self.grid = [[self._biome(elev[y][x], moist[y][x])
                      for x in range(self.width)] for y in range(self.height)]

        # garante uma vila central segura como ponto de spawn
        cx, cy = self.width // 2, self.height // 2
        for y in range(cy - 1, cy + 2):
            for x in range(cx - 2, cx + 3):
                if 0 <= x < self.width and 0 <= y < self.height:
                    self.grid[y][x] = "vila"
        self.spawn = (cx, cy)
        self._populate()

    # ---- nível e elite por posição ----
    def _enemy_level(self, x: int, y: int) -> int:
        """Quanto mais longe da Vila (spawn), maior o nível do inimigo."""
        sx, sy = self.spawn
        dist = max(abs(x - sx), abs(y - sy))
        return 1 + dist // 6

    def _roll_elite(self) -> str | None:
        from .enemy import ELITE_MODS
        if self.rng.random() < 0.13:
            return self.rng.choice(list(ELITE_MODS))
        return None

    def _spawn_enemy(self, x: int, y: int, eid: str):
        from .enemy import Enemy
        return Enemy.spawn(eid, level=self._enemy_level(x, y), elite=self._roll_elite())

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
                        self.enemies[(x, y)] = self._spawn_enemy(x, y, self.rng.choice(pool))
        # posiciona um chefe por região não-segura (escala por distância, sem elite)
        for region in REGIONS:
            if REGIONS[region]["safe"]:
                continue
            bosses = bosses_for_region(region)
            if not bosses:
                continue
            tiles = [(x, y) for y in range(self.height) for x in range(self.width)
                     if self.grid[y][x] == region and (x, y) not in self.enemies]
            if tiles:
                x, y = self.rng.choice(tiles)
                self.enemies[(x, y)] = Enemy.spawn(self.rng.choice(bosses),
                                                   level=self._enemy_level(x, y))

    # ---- consultas ----
    def region_at(self, x: int, y: int) -> str:
        return self.grid[y][x]

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def respawn_enemy(self) -> None:
        """Repõe um inimigo aleatório no mapa (chamado periodicamente)."""
        x, y = self.rng.randrange(self.width), self.rng.randrange(self.height)
        region = self.grid[y][x]
        if REGIONS[region]["safe"] or (x, y) in self.enemies:
            return
        pool = enemies_for_region(region)
        if pool:
            self.enemies[(x, y)] = self._spawn_enemy(x, y, self.rng.choice(pool))

    def random_unsafe_tile(self) -> tuple[int, int] | None:
        """Um tile livre fora de zona segura (para nascer um world boss)."""
        for _ in range(200):
            x, y = self.rng.randrange(self.width), self.rng.randrange(self.height)
            if not REGIONS[self.grid[y][x]]["safe"] and (x, y) not in self.enemies:
                return (x, y)
        return None

    def wander_enemies(self, skip=frozenset(), move_chance: float = 0.25):
        """Move inimigos (exceto chefes) para um tile adjacente ALEATÓRIO.

        Os inimigos vagueiam livremente — NÃO perseguem jogadores. Permanecem no
        mapa, NUNCA entram em zona segura (vila) e não pisam sobre outro inimigo.
        `skip` ignora posições (ex.: inimigos em combate ativo).
        Retorna [(pos_antiga, pos_nova, enemy)] dos que se moveram.
        """
        moves = []
        for pos in list(self.enemies.keys()):
            if pos in skip:
                continue
            enemy = self.enemies[pos]
            if getattr(enemy, "boss", False) or getattr(enemy, "world_boss", False):
                continue
            if self.rng.random() >= move_chance:
                continue
            dx, dy = self.rng.choice(((0, 1), (0, -1), (1, 0), (-1, 0)))
            nx, ny = pos[0] + dx, pos[1] + dy
            if not self.in_bounds(nx, ny):
                continue
            if REGIONS[self.grid[ny][nx]]["safe"]:     # bloqueia a vila/zonas seguras
                continue
            if (nx, ny) in self.enemies:               # tile já ocupado por inimigo
                continue
            del self.enemies[pos]
            self.enemies[(nx, ny)] = enemy
            moves.append((pos, (nx, ny), enemy))
        return moves
