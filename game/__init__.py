"""Lógica de jogo pura (sem rede e sem UI). Reutilizável por servidor e testes."""
from pathlib import Path

# Raiz do projeto e diretórios de dados/save, resolvidos de forma robusta.
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SAVE_DIR = ROOT / "save"
SAVE_DIR.mkdir(exist_ok=True)
