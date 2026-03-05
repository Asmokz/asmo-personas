# ASMO Personas

Quatre services IA autonomes pour le homelab **ASMO-01** : trois personas conversationnels, une gateway API/PWA, et un middleware d'observabilité LLM.

| Service | Rôle | Port | Statut |
|---------|------|------|--------|
| **FEMTO** | Monitoring système & Docker | Discord | ✅ Fonctionnel |
| **GIORGIO** | Médias, notations Jellyfin & recommandations | Discord + `:5555` | ✅ Fonctionnel |
| **ALITA** | Assistante personnelle & briefing matinal | Discord + Olympus | ✅ Fonctionnel |
| **OLYMPUS** | Gateway API + PWA Vue.js | `:8484` | ✅ Fonctionnel |
| **CAUSALITY** | Observabilité LLM (payloads, latences, GPU) | `:1966` | ✅ Fonctionnel |

---

## Architecture

```
asmo-personas/
├── commons/              # Lib partagée
│   └── asmo_commons/
│       ├── api/engine.py         # APIEngine — boucle LLM+tools sans Discord
│       ├── causality/client.py   # CausalityClient — fire-and-forget Redis publisher
│       ├── config/settings.py    # Pydantic settings (Femto/Giorgio/AlitaSettings)
│       ├── discord/base_bot.py   # BaseBot — boucle LLM+tools Discord
│       ├── llm/ollama_client.py  # OllamaClient async avec retry
│       ├── pubsub/redis_client.py # RedisPubSub (asmo.alerts.system, asmo.media.rated)
│       └── tools/registry.py    # @registry.register() decorator pattern
├── femto/                # Persona monitoring (Discord)
├── giorgio/              # Persona média (Discord + webhook Jellyfin)
├── alita/                # Persona assistante (Discord + Olympus)
│   └── scripts/
│       └── label_training.py   # Labelling interactif des échanges (SFT/DPO)
├── olympus/              # Gateway HTTP/WebSocket + PWA Vue.js
│   ├── src/
│   │   ├── main.py              # FastAPI app (lifespan, CORS, static)
│   │   ├── routers/             # chat, conversations, personas, feedback, voice
│   │   ├── personas/            # AlitaPersona, FemtoPersona, GiorgioPersona
│   │   ├── db/                  # OlympusDB (conversations + historique SQLite)
│   │   └── stt/                 # faster-whisper (transcription vocale CPU/int8)
│   └── frontend/                # Vue 3 + Vite + Pinia + PWA (dark/light mode)
├── causality/            # Middleware d'observabilité LLM
│   └── src/
│       ├── main.py              # FastAPI app (API + UI statique)
│       ├── subscriber.py        # Listener Redis asmo.causality
│       ├── hardware.py          # Sampler GPU (pynvml) + swap (psutil)
│       ├── db/manager.py        # SQLite rolling window (7 jours par défaut)
│       └── static/index.html   # SPA dark/rouge — liste des échanges LLM
├── docker-compose.yml
└── .env.example
```

**Stack** : Python 3.11 · FastAPI · Vue 3 · Vite · Pinia · Ollama · Redis · Docker Compose · aiosqlite · yfinance · faster-whisper · numpy · pynvml · psutil

### Flux inter-services (Redis pub/sub)

```
FEMTO  ──► asmo.alerts.system  ──► ALITA (notification si critique)
GIORGIO ──► asmo.media.rated   ──► ALITA (bufferisé pour le briefing)

OllamaClient ──► asmo.causality ──► CAUSALITY (chaque appel LLM, fire-and-forget)
```

---

## Flow end-to-end — ALITA via Olympus

Ce schéma décrit le trajet complet d'un message utilisateur sur la PWA jusqu'à la réponse streamée, avec tous les effets de bord asynchrones.

```
┌─────────────────────────────────────────────────────────────────────┐
│  UTILISATEUR (navigateur)                                           │
│                                                                     │
│  1. Saisit un message dans la PWA Vue 3                             │
│  2. PWA ouvre WS → ws://olympus:8484/api/chat/stream               │
│  3. PWA envoie :                                                    │
│     { conv_id, persona_id: "alita", content, images? }             │
└───────────────────────────┬─────────────────────────────────────────┘
                            │ WebSocket
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│  OLYMPUS (FastAPI :8484)   routers/chat.py                         │
│                                                                     │
│  4. Valide conv_id + persona_id                                     │
│  5. OlympusDB.get_history(conv_id, limit=20)                       │
│     → charge les 20 derniers messages en ordre chronologique       │
│     → supprime les messages orphelins au début (non-user)          │
│     → content NULL → "" (protection anti-HTTP 500 Ollama)         │
└───────────────────────────┬─────────────────────────────────────────┘
                            │ appel Python
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│  AlitaPersona._get_context_prefix(conv_id, content)                │
│                                                                     │
│  6a. LTM RAG — LongTermMemory.search_relevant()                    │
│      - Embed le message via nomic-embed-text (/api/embed)          │
│      - Cosine similarity contre conversation_vectors (alita.db)    │
│      - Seuil 0.72, top-3 échanges pertinents des sessions passées  │
│      - Si trouvé → préfixe "[Mémoire long terme] ..."              │
│                                                                     │
│  6b. URL auto-fetch — FetchUrlTool                                 │
│      - Regex détecte les URLs dans le message (max 2)              │
│      - Fetch via Jina.ai Reader → extrait le texte                 │
│      - Préfixe "[Contenu récupéré depuis ...]"                     │
│                                                                     │
│  6c. Tool hints — injection de rappels ciblés                      │
│      - "souviens-toi / mémorise" → [RAPPEL : appelle memory]       │
│      - "rappelle-moi" → [RAPPEL : appelle reminders]               │
│      - "anytype / note ça" → [RAPPEL : appelle anytype_create_note]│
└───────────────────────────┬─────────────────────────────────────────┘
                            │ context_prefix + user_content
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│  APIEngine._run()   commons/asmo_commons/api/engine.py             │
│                                                                     │
│  7. Construit le message user : { context_prefix + content }       │
│  8. Appende à history                                               │
│                                                                     │
│  ┌── BOUCLE OUTIL (max 5 itérations) ────────────────────────────┐ │
│  │                                                                │ │
│  │  9. CausalityClient.record_call_start()  ◄─── fire-and-forget │ │
│  │     PUBLISH asmo.causality {call_id, conv_id, model,          │ │
│  │                              messages, tool_names, ts_start}  │ │
│  │                                                                │ │
│  │  10. OllamaClient.chat_with_tools()                           │ │
│  │      POST /api/chat → Ollama (ministral-3:14b)                │ │
│  │      payload : { model, messages, tools: [11 defs], stream:F }│ │
│  │                                                                │ │
│  │      ┌── Ollama répond ──────────────────────────────────────┐│ │
│  │      │                                                        ││ │
│  │      │  CAS A — tool_calls présents :                        ││ │
│  │      │    - Yield { type: "tool_start", name, args } → WS   ││ │
│  │      │    - registry.execute(fn_name, fn_args)               ││ │
│  │      │      (weather / stocks / web_search / memory /        ││ │
│  │      │       reminders / anytype / get_stock_quote / ...)    ││ │
│  │      │    - Yield { type: "tool_done", name, result } → WS  ││ │
│  │      │    - Appende tool result à history                    ││ │
│  │      │    - record_call_end() → fire-and-forget              ││ │
│  │      │    → retour au début de la boucle                     ││ │
│  │      │                                                        ││ │
│  │      │  CAS B — réponse texte (pas d'outils) :               ││ │
│  │      │    - Yield { type: "token", content } → WS            ││ │
│  │      │    - Yield { type: "done", entry_id } → WS            ││ │
│  │      │    - record_call_end() → fire-and-forget              ││ │
│  │      │    - _on_exchange_complete() → TrainingLogger          ││ │
│  │      │      (fire-and-forget → alita_training.db)            ││ │
│  │      │    → sort de la boucle                                ││ │
│  │      └────────────────────────────────────────────────────────┘│ │
│  └────────────────────────────────────────────────────────────────┘ │
└───────────────────────────┬─────────────────────────────────────────┘
                            │ retour au router
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│  OLYMPUS router — effets de bord post-échange                      │
│                                                                     │
│  11. OlympusDB.append_messages(conv_id, new_messages)              │
│      → persiste user + assistant + tool messages en SQLite         │
│                                                                     │
│  12. asyncio.create_task(embed_exchange())  ◄── fire-and-forget    │
│      → LongTermMemory.embed_exchange()                              │
│      → nomic-embed-text (/api/embed) → vecteur 768 dim             │
│      → INSERT INTO conversation_vectors (alita.db)                 │
│      (utilisé pour le RAG des prochaines sessions)                 │
│                                                                     │
│  13. asyncio.create_task(_generate_title())  ◄── fire-and-forget   │
│      → si première réponse de la conv (title IS NULL)              │
│      → POST /api/chat Ollama, timeout 90s, num_predict=12          │
│      → OlympusDB.update_title(conv_id, title)                      │
└───────────────────────────┬─────────────────────────────────────────┘
                            │ parallèle
                            ▼
┌─────────────────────────────────────────────────────────────────────┐
│  CAUSALITY (FastAPI :1966)                                          │
│                                                                     │
│  9'. subscriber.py reçoit asmo.causality call_start                │
│      → INSERT into calls (pending)                                  │
│                                                                     │
│  9''. subscriber.py reçoit asmo.causality call_end                 │
│       → HardwareSampler.sample() : GPU util/temp/VRAM (pynvml)    │
│                                     + swap (psutil)                │
│       → UPDATE calls SET duration_ms, tok_s, tokens, gpu_*        │
│       → cleanup_old() si rolling window dépassée                   │
│                                                                     │
│  UI : GET /  → SPA dark/rouge                                      │
│       GET /api/exchanges → JSON list des appels LLM (7j)           │
└─────────────────────────────────────────────────────────────────────┘
```

### Récapitulatif des délais asynchrones

| Opération | Déclencheur | Délai typique |
|-----------|-------------|---------------|
| Causality record | Chaque appel Ollama | < 1 ms (Redis fire-and-forget) |
| LTM embed | Fin d'échange | 1–3 s (Ollama embed en arrière-plan) |
| Title generation | Première réponse | 2–10 s (90s timeout) |
| Training log | Fin d'échange | < 1 ms (SQLite async) |

---

## Olympus — Gateway API + PWA

Olympus est le point d'entrée HTTP/WebSocket pour les trois personas. Il expose aussi l'interface PWA accessible depuis le LAN.

### API REST

| Endpoint | Description |
|----------|-------------|
| `GET /api/personas` | Liste les personas disponibles (id, nom, couleur) |
| `GET /api/conversations?persona_id=alita` | Liste les conversations d'une persona |
| `POST /api/conversations` | Crée une nouvelle conversation `{"persona_id": "alita"}` |
| `GET /api/conversations/{id}` | Détail + historique complet d'une conversation |
| `DELETE /api/conversations/{id}` | Supprime une conversation |
| `POST /api/chat` | Échange non-streamé — retourne `{reply, entry_id, tools_called}` |
| `POST /api/feedback` | Note un échange `{"entry_id": "...", "quality": "good"\|"bad", "correction": "..."}` |
| `POST /api/voice` | Transcription audio (multipart WebM/Opus) → `{"text": "..."}` |
| `GET /health` | Healthcheck `{"status": "ok", "personas": [...]}` |

### WebSocket streaming

```
WS /api/chat/stream
```

Le client envoie un seul message JSON :
```json
{"conv_id": "...", "persona_id": "alita", "content": "...", "images": ["base64..."]}
```

Le serveur retourne des événements JSON :
```json
{"type": "token",      "content": "..."}
{"type": "tool_start", "name": "...", "args": {...}}
{"type": "tool_done",  "name": "...", "result": "..."}
{"type": "done",       "entry_id": "..."}
{"type": "error",      "message": "..."}
```

### Frontend PWA

```bash
cd olympus/frontend
npm install
npm run build    # génère dist/ → servi sur /
npm run dev      # dev server :5173 avec proxy vers :8484
```

Fonctionnalités :
- **Sélecteur de persona** : ALITA, FEMTO, GIORGIO avec avatar et couleur dédiée
- **Historique de conversations** avec liste paginée dans la sidebar
- **Streaming tokens** en temps réel via WebSocket
- **Entrée vocale** push-to-talk (WebM/Opus → faster-whisper)
- **Partage d'images** (redimensionnées à max 1024px → base64)
- **Feedback 👍/👎** avec modal de correction pour la collecte SFT/DPO
- **Dark/light mode** (palette warm : `#1a1410` / `#E85D04`)
- **PWA installable** avec service worker Workbox (network-first API, cache-first assets)

### Déploiement Olympus

```bash
# Build le frontend d'abord (optionnel — l'API fonctionne sans)
cd olympus/frontend && npm install && npm run build && cd -

# Build l'image Docker
docker compose build olympus

# Démarrer Olympus (+ redis requis)
docker compose up -d redis olympus

# Vérifier
curl http://localhost:8484/health
curl http://localhost:8484/api/personas
```

---

## Causality — Observabilité LLM

Causality est un service autonome qui capture chaque appel Ollama de tous les personas via Redis, sans bloquer le chemin critique.

### Architecture

```
OllamaClient (dans chaque persona)
  │  record_call_start() → PUBLISH asmo.causality {call_id, model, messages, tools}
  │  record_call_end()   → PUBLISH asmo.causality {call_id, duration_ms, tokens}
  │
  ▼  (Redis pub/sub, fire-and-forget)
  │
CausalitySubscriber (causality/src/subscriber.py)
  │  reçoit les événements
  │  appelle HardwareSampler à la fin d'un appel :
  │    - GPU : utilisation, température, VRAM (pynvml — RTX 3060)
  │    - swap : utilisé/total (psutil)
  │
  ▼
SQLite /data/causality.db  (rolling window CAUSALITY_RETENTION_DAYS, défaut 7j)
  │
FastAPI :1966
  GET /              → SPA dark/rouge (auto-refresh 30s, lignes expandables)
  GET /api/exchanges → JSON [{call_id, persona, model, duration_ms, tok_s, ...}]
  GET /health        → {"status": "ok"}
```

### Variables d'environnement

```env
CAUSALITY_RETENTION_DAYS=7   # durée de rétention des métriques
CAUSALITY_PORT=1966
CAUSALITY_DB_PATH=/data/causality.db
```

---

## Prérequis

- Docker + Docker Compose v2
- Ollama installé sur l'hôte :
  ```bash
  ollama pull ministral-3:14b   # tous les personas
  ollama pull nomic-embed-text  # ALITA (LTM RAG) + GIORGIO (index sémantique)
  ```
- Pour les bots Discord : trois applications Discord créées sur <https://discord.com/developers/applications>
  (un token par bot)

---

## Déploiement

### 1. Cloner et configurer

```bash
cd /home/asmo
git clone <repo> asmo-personas
cd asmo-personas
cp .env.example .env
nano .env   # remplir les tokens Discord, IDs de canaux et clés API
```

### 2. Récupérer les Channel IDs Discord

Dans Discord : activer le **mode développeur** (Paramètres → Avancé), puis clic droit sur un canal → **Copier l'identifiant**.

### 3. Inviter les bots sur leurs serveurs

Pour chaque bot, dans le portail développeur :
- **OAuth2 → URL Generator** → Scopes : `bot`, `applications.commands`
- Permissions : `Send Messages`, `Read Message History`, `View Channels`
- Activer **Message Content Intent** dans l'onglet *Bot*

### 4. Build et démarrage

```bash
# Build toutes les images
docker compose build

# Initialiser Redis
docker compose up redis -d
python scripts/init_redis.py

# Démarrer tout
docker compose up -d

# Vérifier les logs
docker compose logs -f alita
docker compose logs -f olympus
docker compose logs -f causality
```

### 5. Démarrer uniquement Olympus + Causality (sans bots Discord)

```bash
cd olympus/frontend && npm install && npm run build && cd -
docker compose up -d redis olympus causality
# Interface : http://localhost:8484
# Observabilité : http://localhost:1966
```

### 6. Démarrer uniquement FEMTO

```bash
docker compose up -d redis femto
docker compose logs -f femto
```

---

## Utilisation de FEMTO

### Messages naturels

```
@FEMTO quelle est la place disque ?
@FEMTO combien de RAM il reste ?
@FEMTO montre-moi les conteneurs qui tournent
@FEMTO analyse les logs du conteneur nginx des 6 dernières heures
```

### Commandes préfixées

| Commande | Description |
|----------|-------------|
| `!status` | Résumé rapide : uptime, RAM, disque, conteneurs |
| `!logs <container> [lines]` | Dernières lignes de logs |
| `!analyze <container> [hours]` | Analyse LLM des logs |
| `!containers` | Tous les conteneurs (running + stopped) |
| `!stats` | Utilisation CPU/RAM/réseau par conteneur |

### Rapport automatique

FEMTO collecte les métriques toutes les heures et poste un rapport de 24h chaque jour à l'heure configurée (`FEMTO_HISTORY_REPORT_HOUR`, défaut : 9h00) sur le canal `FEMTO_REPORT_CHANNEL_ID`.

Il publie également une alerte sur Redis (`asmo.alerts.system`) quand un disque dépasse 90% d'utilisation, déclenchant une notification immédiate d'ALITA.

---

## Utilisation de GIORGIO

GIORGIO gère les notifications de fin de visionnage Jellyfin, les notations et les recommandations culturelles.

### Canal dédié

GIORGIO répond à **tous les messages** sur `GIORGIO_RECOMMENDATION_CHANNEL_ID` sans nécessiter de mention. Sur les autres canaux, il faut le taguer.

### Notifications automatiques (webhook Jellyfin)

Quand un utilisateur configuré (`GIORGIO_NOTIFICATION_USERS`) termine un film ou un épisode, Giorgio poste automatiquement un message de notation dans le canal `GIORGIO_CHANNEL_ID`.

Configurer Jellyfin pour envoyer les webhooks vers : `http://<asmo-01>:5555/api/webhook`

### Messages naturels

```
quels sont mes films les mieux notés ?
suggère-moi quelque chose pour une après-midi ensoleillée
qu'est-ce que j'ai regardé récemment ?
combien de films dans la bibliothèque ?
```

### Commandes préfixées

| Commande | Description |
|----------|-------------|
| `!stats` | Statistiques globales : catalogue, visionnages, note moyenne |
| `!toprated [n]` | Top *n* contenus les mieux notés (défaut : 10) |
| `!mostwatched [n]` | Top *n* films/séries les plus vus |
| `!recent [n]` | *n* derniers visionnages avec notes |

### Outils LLM

| Outil | Description |
|-------|-------------|
| `get_top_rated` | Top des contenus les mieux notés |
| `get_most_watched` | Films/séries les plus vus |
| `get_recent_watches` | Activité de visionnage récente |
| `get_global_stats` | Statistiques globales du catalogue |
| `get_recent_media` | Ajouts récents dans Jellyfin |
| `search_media` | Recherche par titre exact dans Jellyfin |
| `browse_library_by_genre` | Parcourt la bibliothèque par genre(s) |
| `semantic_search_library` | Recherche sémantique par description libre (RAG) |
| `get_recommendation` | Recommandation personnalisée via profil de goût |
| `web_search` | Recherche web SearXNG — dernier recours |

### Index sémantique (RAG)

Au démarrage, Giorgio indexe automatiquement toute la bibliothèque Jellyfin dans un index vectoriel SQLite (`/data/giorgio_vectors.db`) via `nomic-embed-text`. Le sync est incrémental.

### API stats (HTTP)

| Endpoint | Description |
|----------|-------------|
| `GET /api/stats` | Statistiques globales JSON |
| `GET /api/stats/most-watched?limit=10` | Plus vus |
| `GET /api/stats/top-rated?limit=10` | Mieux notés |
| `GET /api/stats/recent?limit=10` | Activité récente |
| `POST /api/webhook` | Réception des événements Jellyfin |

---

## Utilisation d'ALITA

ALITA est une assistante personnelle chaleureuse et proactive. Elle répond à **tous les messages** sur son canal dédié (`ALITA_DISCORD_CHANNEL_ID`) sans nécessiter de mention, et envoie un briefing matinal automatique en semaine.

### Briefing matinal automatique

Chaque jour ouvré à l'heure configurée (défaut : 7h00), ALITA collecte en parallèle :

- **Météo** actuelle + prévisions 3 jours
- **Score moto** (analyse des conditions 8h–19h : pluie rédhibitoire, vent, froid, brouillard)
- **Portefeuille boursier** : cours en temps réel, P&L par position, total
- **Rappels** en attente
- **Alertes FEMTO** des dernières heures (via Redis)

Le tout est synthétisé par le LLM en un briefing naturel et personnalisé.

Pour forcer un briefing immédiat : `!briefing`

### Messages naturels

```
c'est bon pour la moto aujourd'hui ?
comment se porte mon portfolio ?
je viens de vendre 1 action AI.PA à 179.48€
cherche les dernières news sur l'IA
rappelle-moi de faire X demain matin
souviens-toi que j'aime le jazz
note dans anytype : réunion jeudi à 14h
```

### Commandes préfixées

| Commande | Description |
|----------|-------------|
| `!briefing` | Génère et poste immédiatement le briefing complet |
| `!rappels` | Liste les rappels en attente |
| `!prefs` | Liste les préférences mémorisées |

### Outils disponibles (11 outils)

| Outil | Description |
|-------|-------------|
| `get_current_weather` | Météo actuelle (OpenWeatherMap) |
| `get_weather_forecast` | Prévisions 1–5 jours |
| `should_i_ride` | Score moto 0–10 basé sur les conditions 8h–19h |
| `get_portfolio_info` | P&L complet du portefeuille (depuis la DB SQLite) |
| `get_stock_quote` | Cours d'une action individuelle |
| `update_portfolio_position` | Achat / vente / correction manuelle d'une position |
| `web_search` | Recherche web via SearXNG |
| `memory` | Mémoire persistante : `remember` / `recall` / `list` |
| `reminders` | Rappels : `add` / `list` / `complete` |
| `anytype_create_note` | Crée une note, page ou mémo dans Anytype |
| `anytype_read` | Lit Anytype : `search` / `get` / `list` |

**Fonctionnalités automatiques** (pas des outils — s'activent avant l'appel LLM) :
- **URL auto-fetch** : Jina.ai Reader, max 2 URLs détectées dans le message
- **LTM RAG** : cosine similarity sur les échanges passés (seuil 0.72, top-3)
- **Tool hints** : injection de rappels ciblés selon les patterns détectés dans le message

### Portefeuille boursier

Le portefeuille est stocké en base SQLite (`/data/alita.db`), pas dans une variable d'environnement. ALITA gère les achats et ventes en temps réel via l'outil `update_portfolio_position` :

```
je viens d'acheter 5 actions AAPL à 185€
j'ai vendu 1 action AI.PA à 179.48€, il m'en reste 2
corrige ma position AIR.PA : 3 actions à 186€ de PRU
```

**Migration** : si `ALITA_PORTFOLIO` est défini dans `.env`, les positions sont importées automatiquement dans la DB au premier démarrage (opération unique).

### Configurer Anytype

1. Démarrer le serveur Anytype local (`anytype-heart` ou desktop avec API activée)
2. Renseigner dans `.env` :
   ```env
   ALITA_ANYTYPE_URL=http://127.0.0.1:31012
   ALITA_ANYTYPE_API_KEY=xxx
   ALITA_ANYTYPE_SPACE_ID=xxx
   ```

### Mémoire persistante

**`/data/alita.db`** — base opérationnelle :
- **Préférences** : clé/valeur persistantes entre les sessions, injectées dans le system prompt
- **Portefeuille boursier** : positions avec quantités et PRU
- **Rappels** : avec date d'échéance optionnelle
- **LTM (Long-Term Memory)** : embeddings des échanges passés (`nomic-embed-text`, 768 dim) pour enrichir le contexte par similarité cosinus (seuil 0.72, top-3)

**`/data/alita_training.db`** — collecte de données d'entraînement :
- Capture automatique de chaque échange complet (format Mistral chat + méta)
- Champ `quality` (NULL / `good` / `bad`) pour le labelling SFT/DPO
- Champ `correction` pour les paires DPO
- Script de labelling interactif : `docker exec -it asmo-alita python /app/scripts/label_training.py`

---

## Configuration avancée

### Modifier le modèle LLM

```bash
# .env
ASMO_OLLAMA_MODEL=ministral-3:14b
ALITA_OLLAMA_MODEL=ministral-3:14b
GIORGIO_EMBED_MODEL=nomic-embed-text
ALITA_EMBED_MODEL=nomic-embed-text
```

Modèles recommandés avec tool calling : `ministral-3:14b`, `llama3.1:8b`, `qwen2.5:7b`

### Métriques hôte vs container (FEMTO)

Par défaut, FEMTO lit `/proc` pour obtenir les métriques de l'hôte (RAM, CPU, uptime). Pour la consommation disque de l'hôte :

**Option A** — Bind mount du système de fichiers hôte :
```yaml
# dans docker-compose.yml, service femto :
volumes:
  - /:/host:ro
```
Puis modifier `system_metrics.py` pour utiliser `df /host`.

---

## Développement

### Tester localement sans Docker

```bash
# Installer la lib commons en éditable
pip install -e commons/

# Variables d'environnement pour dev
export ALITA_DISCORD_TOKEN=xxx
export ASMO_OLLAMA_BASE_URL=http://localhost:11434
export ASMO_REDIS_URL=redis://localhost:6379
export ASMO_LOG_JSON=false

# Lancer ALITA
cd alita && pip install -e . && python -m src.main

# Lancer Olympus
cd olympus && pip install -e . && python -m src.main
```

### Ajouter un outil

La structure est identique pour les trois bots :

1. Implémenter la méthode async dans le fichier de tool approprié
2. L'enregistrer dans `XxxBot._register_tools()` avec `@reg.register(...)`
3. Rebuild : `docker compose build <bot> && docker compose up -d <bot>`

```python
@reg.register(
    "nom_de_loutil",
    "Description claire pour le LLM — elle guide quand appeler cet outil.",
    parameters={
        "type": "object",
        "properties": {
            "param1": {"type": "string", "description": "..."},
        },
        "required": ["param1"],
    },
)
async def nom_de_loutil(param1: str) -> str:
    # Toujours async, retourne une str, catch toutes les exceptions
    return await self.xxx.faire_quelque_chose(param1)
```

---

## Sécurité

- **Whitelist stricte** : seules les commandes listées dans `CommandExecutor.ALLOWED_COMMANDS` sont exécutables. Aucune exécution shell arbitraire (`shell=False` partout).
- **Read-only** : FEMTO ne modifie pas l'état du système.
- **Socket Docker en RO** : monté en `:ro` — impossible d'écrire dans le socket.
- **Secrets en env vars** : aucun secret en dur dans le code.
- **Pub/sub non-bloquant** : Redis indisponible → dégradation gracieuse, le bot continue de fonctionner.
- **Timeout sur chaque commande** : configurable via `FEMTO_CMD_TIMEOUT`.

---

## Dépannage

| Symptôme | Cause probable | Solution |
|----------|---------------|----------|
| Bot ne répond pas | Token invalide ou intents manquants | Vérifier le token et activer **Message Content Intent** dans le portail développeur |
| `OllamaError: Connection failed` | Ollama non démarré | `systemctl start ollama` sur l'hôte |
| `redis.exceptions.ConnectionError` | Redis non démarré | `docker compose up -d redis` |
| ALITA ne répond pas sur le canal | `ALITA_DISCORD_CHANNEL_ID` manquant | Renseigner l'ID du canal dédié dans `.env` |
| GIORGIO ne répond pas sur le canal | `GIORGIO_RECOMMENDATION_CHANNEL_ID` manquant | Renseigner l'ID dans `.env` |
| Score moto toujours indisponible | Clé API météo absente | Vérifier `ALITA_WEATHER_API_KEY` |
| Portfolio ALITA vide | Première utilisation | Parler directement à ALITA pour déclarer les positions, ou renseigner `ALITA_PORTFOLIO` en JSON pour la migration initiale |
| `ExecutorError: Command 'X' is not in the whitelist` | Commande non autorisée | Ajouter à `ALLOWED_COMMANDS` dans `executor.py` si légitime |
| Index sémantique GIORGIO vide | `nomic-embed-text` non installé | `ollama pull nomic-embed-text` puis `docker compose restart giorgio` |
| Causality vide (aucun échange) | Container utilise une ancienne image | `docker compose up -d --force-recreate olympus` |
| Titres de conversation non générés | Ollama occupé au moment de la génération | Timeout passé à 90s — si persiste, vérifier `docker compose logs olympus` |

---

## Roadmap

- [x] FEMTO : monitoring système complet
- [x] FEMTO → ALITA : alertes Redis sur disque critique
- [x] GIORGIO : système de notation avec boutons Discord
- [x] GIORGIO → ALITA : publication des notations via Redis
- [x] GIORGIO : canal dédié sans mention
- [x] GIORGIO : recherche web SearXNG (fallback)
- [x] GIORGIO : index sémantique RAG (nomic-embed-text + SQLite)
- [x] GIORGIO : browse par genre Jellyfin (résultats réels, anti-hallucination)
- [x] ALITA : briefing matinal complet (météo, moto, bourse, rappels, alertes)
- [x] ALITA : score moto intelligent (analyse 8h–19h, pluie rédhibitoire)
- [x] ALITA : portefeuille boursier persistant en SQLite
- [x] ALITA : recherche web SearXNG
- [x] ALITA : mémoire persistante SQLite (préférences + rappels)
- [x] ALITA : LTM mémoire long terme via RAG (nomic-embed-text, conversation_vectors)
- [x] ALITA : auto-fetch URLs dans le contexte (Jina.ai Reader)
- [x] ALITA : intégration Anytype self-hosted (notes, pages, base de connaissance)
- [x] ALITA : collecte de données d'entraînement SFT/DPO
- [x] **OLYMPUS v0.2.0** : gateway FastAPI HTTP/WebSocket
- [x] **OLYMPUS** : PWA Vue 3 + Pinia + Vite (dark/light, streaming, push-to-talk, images)
- [x] **OLYMPUS** : STT faster-whisper CPU/int8 (WebM/Opus → texte)
- [x] **OLYMPUS** : feedback 👍/👎 avec correction (SFT/DPO depuis la PWA)
- [x] **CAUSALITY** : middleware d'observabilité LLM (payloads, latences, GPU/swap)
- [x] **CAUSALITY** : SPA dark/rouge — liste des échanges avec détail expandable
- [ ] ALITA : intégration Google Calendar / Nextcloud CalDAV
- [ ] ALITA : résumé d'actualités via flux RSS
- [ ] GIORGIO : sync périodique de l'index sémantique
- [ ] OLYMPUS : notifications push PWA (rappels ALITA, alertes FEMTO)
- [ ] OLYMPUS : mode multi-utilisateur avec authentification
