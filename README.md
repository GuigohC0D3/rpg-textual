# ⚔ RPG Textual Cooperativo (LAN)

RPG multiplayer jogável por **2 a 8 jogadores** no terminal, em rede local.
Um jogador hospeda o servidor; os demais conectam pelo IP/porta. Interface em
**Textual (TUI)**, arquitetura **cliente-servidor** com **servidor autoritativo**
e **zero dependências** além do Textual.

---

## 🚀 Como rodar

```bash
pip install -r requirements.txt          # instala Textual

# 1) HOST — quem hospeda a partida:
python -m server.server                  # escuta em 0.0.0.0:7777 (toda a LAN)
#   descubra seu IP da LAN:  ipconfig (Windows) / ip addr (Linux)

# 2) JOGADORES — em cada terminal/máquina:
python -m client.app
#   informe nome, classe, COR e o IP/porta do host (7777)
#   o próprio host também joga com IP 127.0.0.1
```

No lobby você escolhe **nome**, **classe**, uma **cor de identificação** (como
seu `@` e seu `P` aparecem no mapa) e o endereço do servidor.

---

## 🎮 Controles (teclado)

| Tecla              | Ação                                                        |
|--------------------|-------------------------------------------------------------|
| `W A S D` / setas  | Mover no mapa                                               |
| `1`                | Combate: **Atacar**                                         |
| `2`                | Combate: **Defender** (reduz o próximo dano pela metade)    |
| `3`                | Combate: **Habilidade** (skill da classe)                  |
| `4`                | Combate: **Poção** · **fora de combate**: usa Poção de Vida |
| `5`                | Combate: **Fugir**                                          |
| `6`                | Combate: **Suprema** (ult, com recarga)                    |
| `R`                | **Descansar** (só na Vila — restaura HP/Mana)              |
| `Enter`            | Focar o chat (digite mensagem ou `/comando`)               |
| `Esc`              | Voltar do chat/fechar modal                                |

---

## 💬 Comandos de chat

### Geral / social
| Comando | Descrição |
|---------|-----------|
| `/help` | Lista os comandos |
| `/who` | Jogadores online |
| `/msg <nome> <txt>` (ou `/w`) | Mensagem privada |
| `/roll [N]` | Rola um dado d`N` (padrão d20), anunciado a todos |
| `/emote <txt>` | Ação/emote no chat global |
| `/party` | Cria um grupo |
| `/party invite <nome>` | Convida para o grupo |
| `/party accept` | Aceita um convite pendente |

### Personagem / itens
| Comando | Descrição |
|---------|-----------|
| `/inventario` (ou `/inv`) | Abre o **modal de inventário** (equipar/usar/organizar) |
| `/equip <id>` | Equipa um item |
| `/use <id>` | Usa um consumível |
| `/quests` | Missões ativas e disponíveis |
| `/accept <id>` | Aceita uma missão |
| `/rest` | Descansa na Vila (HP/Mana cheios) |

### Economia / progressão
| Comando | Descrição |
|---------|-----------|
| `/shop` (ou `/loja`) | Abre o **modal da loja** (comprar/vender) |
| `/shop buy <id> [qtd]` | Compra direto pelo chat |
| `/shop sell <id> [qtd]` | Vende direto pelo chat (50% do valor) |
| `/forge <id>` | **Forja**: melhora um equipamento (+N) na Vila |
| `/trade <nome>` | Inicia troca; depois: `accept`, `gold <n>`, `item <id> [qtd]`, `confirm`, `cancel` |

### Guildas / ranking
| Comando | Descrição |
|---------|-----------|
| `/guild create <nome>` | Funda uma guilda |
| `/guild join <nome>` | Entra numa guilda |
| `/guild leave` | Sai da guilda |
| `/guild info <nome>` | Detalhes de uma guilda |
| `/guild list` | Lista as guildas |
| `/ranking` (ou `/rank`) | Top 10 por nível e XP (online + saves) |

> A loja e a forja só funcionam em **zona segura (Vila)**. Loja e inventário
> abrem como **modais interativos** (↑↓ para navegar, Enter para agir, Esc fecha).

---

## 🧙 Classes

| Classe | Perfil | Habilidade | Suprema (ult) |
|--------|--------|------------|----------------|
| **Guerreiro** | Muito HP e defesa, golpes pesados | Golpe Brutal | Fúria Sangrenta (+sangramento) |
| **Mago** | Dano mágico altíssimo, frágil | Bola de Fogo (+queimadura) | Meteoro (+queimadura forte) |
| **Arqueiro** | Rápido, crítico alto | Tiro Certeiro (+sangramento) | Chuva de Flechas (+sangramento) |
| **Curandeiro** | Cura e suporte | Cura Divina | Luz Restauradora (+regeneração) |

Cada classe tem **uma skill barata** e **uma suprema cara com recarga** em turnos.

---

## 🗡 Sistemas de jogo

### Combate tático (turnos, cooperativo)
- Encontros acontecem por inimigo num tile; vários jogadores no mesmo tile lutam
  **juntos**. Cada ação é resolvida pelo servidor e o inimigo **retalia contra
  quem agiu**. XP/ouro são divididos; saque é rolado individualmente.
- **Ordem por velocidade (estilo Pokémon)**: quem tiver **`SPD` (speed) maior
  golpeia primeiro** na rodada. Se o inimigo for mais rápido, ele ataca **antes**
  da sua ação — o painel de combate mostra `⚡ SPD seu vs inimigo` e quem começa.
- **Mitigação por defesa**: dano = atk · (1 − def/(def+50)) · variância ±15%,
  com **crítico ×2**.
- **Efeitos de status**: veneno, queimadura, sangramento (**dano por turno**),
  **atordoamento** (sempre perde o turno), **paralisia** (30% de chance de perder
  o turno a cada rodada), **regeneração** (cura por turno) e buffs temporários de
  **força/defesa** (elixires). Tickam a cada turno e valem para jogadores **e**
  inimigos.
- **Suprema (ult)** por classe, com **cooldown**; skills e ults podem **infligir
  status** ao inimigo.

### Inimigos & dificuldade
- 6 regiões geram inimigos próprios; **chefes** têm **arte ASCII** e habilidades.
- **Escala por distância**: quanto mais longe da Vila, maior o **nível** do
  inimigo (HP/ATK/recompensa).
- **Elites** (~13%) com modificadores — Veloz, Blindado, Venenoso, **Brutal**
  (atordoa), **Paralisante** (paraliza + rápido), Colossal — com nome destacado,
  atributos e loot melhores. Alguns inimigos têm aflição própria (ex.: Escorpião
  envenena, Espectro paralisa).
- **Movimento livre**: inimigos vagueiam aleatoriamente pelo mapa (não perseguem
  o jogador) e nunca entram na Vila.
- **Chefes de mundo**: nascem periodicamente, **escalam com o nº de jogadores
  online**, são **anunciados no chat global** e largam tesouro garantido.
- **Domar (pets)**: chance de domar um inimigo comum derrotado; o pet ataca junto.
- **Penalidade de morte**: ao cair, você perde parte do **ouro e do XP** e
  renasce na Vila.

### Itens, loot & forja
- **Raridades**: comum, raro, épico, lendário (cores na ficha/loja).
- Slots: arma, armadura, escudo, amuleto, anel + consumíveis e materiais.
- **Stats à vista**: inventário e loja mostram os bônus de cada item
  (`ATK`, `DEF`, `HP`, `MP`, `Crít`) e uma **seta de comparação ▲/▼** com o que
  está equipado no mesmo slot — fácil saber qual arma/armadura é melhor.
- **Drops de chefe garantidos**: bosses largam seu item mais forte; world bosses
  largam um extra.
- **Forja (`/forge`)**: gasta ouro + **Essência Monstruosa** (cai de elites/chefes)
  para subir um equipamento até **+5** (bônus +8% por nível).
- **Elixires de buff** (força/defesa) usados em combate.

### Economia & comércio
- **Loja (Vila)**: compra de consumíveis e equipamentos comuns/raros; venda de
  qualquer item a 50%. Materiais e épicos/lendários ficam fora da venda (só loot).
- **Troca entre jogadores (`/trade`)**: ofertas de ouro/itens, **dupla
  confirmação**, **swap atômico** com revalidação e cancelamento ao desconectar.

### Mundo & progressão
- **Mapa por ruído de Perlin**: dois campos (elevação + umidade) com fBm definem
  biomas orgânicos e contíguos; Vila central é zona segura/spawn. Reprodutível
  pela seed.
- **Missões** kill/boss com recompensa de XP, ouro e item.
- **Ciclo dia/noite** e **clima** dinâmicos (tick de 5s).
- **Bênção de XP**: evento global aleatório que dobra o XP por um tempo.
- **Grupos (party)**, **guildas** persistentes e **ranking** global.

### Interface
- Tela dividida: **mapa** (preenche dinamicamente o painel), **chat**, **ficha**
  e **log de combate**. A ficha mostra ATK/DEF/**SPD**/Crít. Painel de combate
  mostra HP do inimigo, arte ASCII, status ativos, a **comparação de velocidade
  (quem ataca primeiro)** e a suprema.
- **Modais** interativos de **loja** e **inventário** (equipar/usar/organizar por
  categoria e raridade).
- **Cor de identificação** por jogador, no mapa e na ficha.

---

## 🏗 Arquitetura

```
common/          protocolo compartilhado (JSON por linha sobre TCP)
  protocol.py    tipos de mensagem + encode/decode

server/          SERVIDOR AUTORITATIVO (asyncio)
  network.py     transporte: conexões, enquadramento, callbacks
  world.py       GameState: mapa, sessões, combates, grupos, guildas, clima, dia/noite
  server.py      orquestração: dispatch, broadcast, comandos, tick do mundo

client/          CLIENTE (Textual TUI)
  app.py         App + GameScreen + worker de rede (reconexão automática)
  screens.py     ConnectScreen (lobby: nome, classe, cor, IP, porta)
  widgets.py     Sidebar · MapView · CombatPanel
  modals.py      ShopModal · InventoryModal (modais interativos)

game/            LÓGICA PURA (sem rede/UI — testável isoladamente)
  classes.py player.py enemy.py combat.py items.py quests.py
  map.py (Perlin) guild.py ranking.py

data/            items.json · enemies.json · quests.json
save/            persistência por personagem (JSON, autosave a cada 5s) + guilds.json
```

### Modelo de sincronização
- **Servidor é a única fonte da verdade.** O cliente envia *intenções*
  (`move`, `combat`, `chat`, `action`, `view`) e *renderiza* o estado recebido.
- **Protocolo:** JSON delimitado por `\n` sobre TCP (`common/protocol.py`).
  Cliente→Servidor: `join, move, chat, combat, action, view, ping`.
  Servidor→Cliente: `welcome, state, you, chat, log, combat, error`.
- **Tempo real:** ao mover, o servidor reenvia o `state` (janela do mapa) ao
  jogador e aos próximos. A **janela do mapa se ajusta ao tamanho do painel**
  (negociação cliente↔servidor via `view`).
- **Tick do mundo (5s):** relógio (dia/noite), clima, respawn, **movimento
  aleatório dos inimigos**, **evento de XP**, **chefe de mundo** e autosave de todos.
- **Reconexão:** queda → cliente reconecta com *backoff* exponencial e refaz o
  `join`; o servidor reconhece o jogador pelo nome e restaura a sessão.

---

## 🧪 Testes

`game/` é lógica pura e foi validada isoladamente (geração de mundo por Perlin,
leveling, combate com status/ult, escala/elites, forja, drops de chefe). A camada
de rede foi testada com clientes simulados (join, chat, movimento, combate,
troca, loja, world boss, reconexão) e a UI em **modo headless** do Textual
(modais, painel de combate, viewport dinâmico, seleção de cor).
