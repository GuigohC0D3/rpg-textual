# ⚔ RPG Textual Cooperativo (LAN)

RPG multiplayer jogável por **2 a 8 jogadores** no terminal, em rede local.
Um jogador hospeda o servidor; os demais conectam pelo IP/porta. Interface em
**Textual (TUI)**, arquitetura **cliente-servidor** com servidor autoritativo.

---

## 🚀 Como rodar

```bash
pip install -r requirements.txt          # instala Textual

# 1) HOST — quem hospeda a partida:
python -m server.server                  # escuta em 0.0.0.0:7777 (toda a LAN)
#   descubra seu IP da LAN:  ipconfig (Windows) / ip addr (Linux)

# 2) JOGADORES — em cada terminal/máquina:
python -m client.app
#   informe nome, classe, IP do host e porta (7777)
#   o próprio host também joga com IP 127.0.0.1
```

### Controles
| Tecla        | Ação                                            |
|--------------|-------------------------------------------------|
| `W A S D` / setas | Mover no mapa                              |
| `Enter`      | Focar o chat (digite mensagem ou `/comando`)    |
| `Esc`        | Voltar do chat para o movimento                 |
| `1`-`5`      | Em combate: Atacar / Defender / Habilidade / Poção / Fugir |
| `R`          | Descansar (só na Vila — restaura HP/Mana)       |

### Comandos de chat
`/help` `/who` `/msg <nome> <txt>` `/party [invite <nome>|accept]` `/roll [N]`
`/emote <txt>` `/trade <nome>` `/quests` `/accept <id>` `/equip <id>` `/use <id>` `/rest`

---

## 🏗 Arquitetura

```
common/          protocolo compartilhado (JSON por linha sobre TCP)
  protocol.py    tipos de mensagem + encode/decode

server/          SERVIDOR AUTORITATIVO (asyncio)
  network.py     transporte: aceita conexões, enquadra mensagens, callbacks
  world.py       GameState: mapa, sessões, combates, grupos, clima, dia/noite
  server.py      orquestração: dispatch, broadcast, comandos, tick do mundo

client/          CLIENTE (Textual TUI)
  app.py         App + GameScreen + worker de rede (reconexão automática)
  screens.py     ConnectScreen (lobby: nome, classe, IP, porta)
  widgets.py     Sidebar, MapView, CombatPanel

game/            LÓGICA PURA (sem rede/UI — testável isoladamente)
  classes.py player.py enemy.py combat.py items.py quests.py map.py

data/            items.json · enemies.json · quests.json
save/            persistência por personagem (JSON, autosave a cada 5s)
```

### Modelo de sincronização
- **Servidor é a única fonte da verdade.** O cliente nunca decide regras: só
  envia *intenções* (`move`, `combat`, `chat`) e *renderiza* o estado recebido.
- **Protocolo:** mensagens JSON delimitadas por `\n` sobre TCP (`common/protocol.py`).
  Cliente→Servidor: `join, move, chat, combat, action, ping`.
  Servidor→Cliente: `welcome, state, you, chat, log, combat, error`.
- **Tempo real:** ao mover, o servidor reenvia o `state` (janela do mapa ao redor)
  ao jogador e a todos os jogadores próximos, propagando movimentos na hora.
- **Tick do mundo (5s):** avança o relógio (ciclo dia/noite), sorteia clima,
  reposiciona inimigos (respawn) e faz autosave de todos os personagens.
- **Reconexão:** se a conexão cai, o cliente reconecta com *backoff* exponencial
  e refaz o `join`; o servidor reconhece o jogador pelo nome e restaura a sessão.

### Combate cooperativo
Encontros (`game/combat.py`) acontecem por inimigo num tile. Vários jogadores no
mesmo tile lutam juntos: cada ação é resolvida pelo servidor e o inimigo retalia
contra quem agiu. XP/ouro são divididos entre participantes; saque é rolado
individualmente; o progresso de missões é atualizado por jogador.

---

## ✅ Implementado
Interface dividida (mapa, chat, ficha, log de combate) · multiplayer LAN
cliente-servidor com reconexão · 4 classes (Guerreiro/Mago/Arqueiro/Curandeiro)
com habilidades · mundo procedural (Voronoi) com 6 regiões · inimigos com IA +
**chefes com arte ASCII** · combate por turnos co-op (atacar/defender/habilidade/
item/fugir) · inventário, equipamentos e raridades · missões (kill/boss) com
recompensas · chat global + privado + comandos · grupos (party) · salvamento
JSON com autosave · clima · ciclo dia/noite.

## 🗺 Roadmap (extras ainda não implementados)
Comércio completo entre jogadores (UI de troca) · pets · guildas · ranking ·
eventos aleatórios · efeitos sonoros. Os ganchos (`/trade`, party, tick) já
existem para facilitar a extensão.

## 🧪 Testes
`game/` é lógica pura e foi validada isoladamente (geração de mundo, leveling,
combate). A camada de rede foi testada com clientes simulados (join, chat,
movimento, combate, reconexão) e a UI em modo headless do Textual.
