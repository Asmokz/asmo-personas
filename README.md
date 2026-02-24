# ASMO Personas

Trois bots Discord autonomes pour le homelab **ASMO-01**.

| Bot | Rôle | Statut |
|-----|------|--------|
| **FEMTO** | Monitoring système & Docker | ✅ Fonctionnel |
| **GIORGIO** | Médias, notations Jellyfin & recommandations | ✅ Fonctionnel |
| **ALITA** | Assistante personnelle & briefing matinal | ✅ Fonctionnel |

## Architecture

```
asmo-personas/
├── commons/              # Lib partagée (OllamaClient, BaseBot, ToolRegistry, RedisPubSub…)
├── femto/                # Bot monitoring
├── giorgio/              # Bot média
├── alita/                # Bot assistante personnelle
├── scripts/
│   └── init_redis.py
├── docker-compose.yml
└── .env.example
```

**Stack** : Python 3.11 · discord.py · Ollama · Redis · Docker Compose · aiosqlite · yfinance · FastAPI

### Flux inter-personas (Redis pub/sub)

```
FEMTO ──► asmo.alerts.system ──► ALITA (notification immédiate si critique)
GIORGIO ──► asmo.media.rated  ──► ALITA (bufferisé pour le briefing)
```

---

## Prérequis

- Docker + Docker Compose v2
- Ollama installé sur l'hôte :
  ```bash
  ollama pull mistral:7b        # FEMTO + GIORGIO
  ollama pull mistral-nemo      # ALITA (recommandé pour la qualité)
  ```
- Trois applications Discord créées sur <https://discord.com/developers/applications>
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
docker compose logs -f femto
docker compose logs -f alita
docker compose logs -f giorgio
```

### 5. Démarrer uniquement FEMTO (recommandé pour commencer)

```bash
docker compose up -d redis femto
docker compose logs -f femto
```

---

## Utilisation de FEMTO

### Messages naturels (mentionner le bot)

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

GIORGIO gère les notifications de fin de visionnage Jellyfin, les notations et les recommandations culturelles. Il partage la base MariaDB de l'ancien conteneur `giorgio-bot`.

### Notifications automatiques (webhook Jellyfin)

Quand un utilisateur configuré (`GIORGIO_NOTIFICATION_USERS`) termine un film ou un épisode, Giorgio poste automatiquement un message de notation dans le canal `GIORGIO_CHANNEL_ID` :

```
🎬 Bellissimo! asmo vient de terminer Dune (2021)!

Alors, caro mio, c'était comment? Note cette œuvre de 1 à 10!
[1][2][3][4][5]
[6][7][8][9][10]
```

Giorgio réagit différemment selon chaque note (de *"Madonna! quelle horreur"* à *"Perfetto! chef-d'œuvre absolu"*). Chaque notation est également publiée sur Redis (`asmo.media.rated`) pour être incluse dans le briefing ALITA.

Configurer Jellyfin pour envoyer les webhooks vers : `http://<asmo-01>:5555/api/webhook`

### Messages naturels (mentionner le bot)

```
@GIORGIO quels sont mes films les mieux notés ?
@GIORGIO suggère-moi quelque chose pour une soirée détente
@GIORGIO qu'est-ce que j'ai regardé récemment ?
@GIORGIO combien de films dans la bibliothèque ?
@GIORGIO cherche Blade Runner dans Jellyfin
```

### Commandes préfixées

| Commande | Description |
|----------|-------------|
| `!stats` | Statistiques globales : catalogue, visionnages, note moyenne |
| `!toprated [n]` | Top *n* contenus les mieux notés (défaut : 10) |
| `!mostwatched [n]` | Top *n* films/séries les plus vus, épisodes agrégés par série |
| `!recent [n]` | *n* derniers visionnages avec notes (défaut : 10) |

### API stats (HTTP)

| Endpoint | Description |
|----------|-------------|
| `GET /api/stats` | Statistiques globales JSON |
| `GET /api/stats/most-watched?limit=10` | Plus vus (séries agrégées) |
| `GET /api/stats/top-rated?limit=10&min_ratings=1` | Mieux notés |
| `GET /api/stats/recent?limit=10` | Activité récente |
| `GET /api/stats/user/<jellyfin_id>` | Stats d'un utilisateur |
| `POST /api/webhook` | Réception des événements Jellyfin |

---

## Utilisation d'ALITA

ALITA est une assistante personnelle chaleureuse et proactive. Elle répond à **tous les messages** sur son canal dédié (`ALITA_DISCORD_CHANNEL_ID`) sans nécessiter de mention, et envoie un briefing matinal automatique en semaine.

### Briefing matinal automatique

Chaque jour ouvré à l'heure configurée (défaut : 7h00), ALITA collecte en parallèle :

- **Météo** actuelle + prévisions 3 jours
- **Score moto** (analyse des conditions 8h–19h : pluie rédhibitoire, vent, froid, brouillard)
- **Portefeuille boursier** : cours en temps réel, P&L par position, total
- **Capteurs Home Assistant** : température, humidité, énergie
- **Rappels** en attente
- **Alertes FEMTO** des dernières heures (via Redis)

Le tout est synthétisé par le LLM en un briefing naturel et personnalisé.

Pour forcer un briefing immédiat : `!briefing`

### Messages naturels (sur le canal dédié ou en mention)

```
c'est bon pour la moto aujourd'hui ?
comment se porte mon portfolio ?
éteins les lumières du salon
mets de la musique
cherche les dernières news sur l'IA
rappelle-moi de faire X demain matin
souviens-toi que j'aime le jazz
```

ALITA utilise ses outils automatiquement selon le contexte — pas besoin de formuler une requête explicite.

### Commandes préfixées

| Commande | Description |
|----------|-------------|
| `!briefing` | Génère et poste immédiatement le briefing complet |
| `!rappels` | Liste les rappels en attente |
| `!prefs` | Liste les préférences mémorisées |
| `!spotify-auth` | Génère l'URL d'authentification Spotify (à faire une seule fois) |

### Outils disponibles

| Outil | Description |
|-------|-------------|
| `get_current_weather` | Météo actuelle (OpenWeatherMap) |
| `get_weather_forecast` | Prévisions 1–5 jours |
| `should_i_ride` | Score moto 0–10 basé sur les conditions 8h–19h |
| `get_portfolio_summary` | P&L complet du portefeuille (`ALITA_PORTFOLIO`) |
| `get_stock_quote` | Cours d'une action individuelle |
| `get_ha_states` | Liste les entités Home Assistant (filtrable par domaine) |
| `get_ha_entity` | État détaillé d'une entité HA |
| `call_ha_service` | Appelle un service HA (turn_on, turn_off, toggle, scene…) |
| `get_ha_sensors_summary` | Résumé des capteurs clés (température, humidité, énergie) |
| `web_search` | Recherche web via SearXNG (pour les questions d'actualité) |
| `get_now_playing` | Titre en cours sur Spotify |
| `control_spotify` | play / pause / next / previous |
| `search_spotify` | Recherche track, artiste, playlist |
| `get_recent_tracks` | Derniers morceaux écoutés |
| `add_to_spotify_queue` | Ajoute un morceau à la file |
| `remember` | Mémorise une préférence (persiste entre sessions) |
| `recall` | Récupère une préférence mémorisée |
| `list_preferences` | Liste toutes les préférences |
| `add_reminder` | Crée un rappel (avec date optionnelle) |
| `get_reminders` | Liste les rappels en attente |
| `complete_reminder` | Marque un rappel comme terminé |

### Configurer le portefeuille boursier

Dans `.env`, renseigner `ALITA_PORTFOLIO` au format JSON :

```env
ALITA_PORTFOLIO=[{"symbol":"AAPL","shares":10,"avg_price":150.0},{"symbol":"MC.PA","shares":2,"avg_price":700.0}]
```

Fonctionne avec tous les tickers Yahoo Finance (actions US, françaises `.PA`, ETFs…).

### Configurer Home Assistant

1. Dans HA : **Profil → Jetons d'accès longue durée → Créer un token**
2. Renseigner dans `.env` :
   ```env
   ALITA_HA_URL=http://homeassistant:8123
   ALITA_HA_TOKEN=eyJ...
   ```

Domaines autorisés pour `call_ha_service` : `light`, `switch`, `scene`, `climate`, `input_boolean`, `script`, `automation`.

### Configurer Spotify

L'authentification Spotify nécessite un flow OAuth2 initial (une seule fois) :

1. Créer une application sur <https://developer.spotify.com/dashboard>
2. Ajouter `http://localhost:8888/spotify/callback` dans les **Redirect URIs**
3. Renseigner dans `.env` :
   ```env
   ALITA_SPOTIFY_CLIENT_ID=xxx
   ALITA_SPOTIFY_CLIENT_SECRET=xxx
   ```
4. Sur Discord : taper `!spotify-auth` → ALITA génère une URL d'autorisation
5. Visiter l'URL, autoriser l'accès → redirection vers `localhost:8888/spotify/callback`
6. Le refresh token est sauvegardé automatiquement en base SQLite

Le token est renouvelé automatiquement à chaque démarrage.

### Mémoire persistante

ALITA maintient une base SQLite (`/data/alita.db`) avec :
- **Préférences** : clé/valeur persistantes entre les sessions, injectées dans le system prompt
- **Historique** des conversations (7 jours glissants, purgé automatiquement au démarrage)
- **Rappels** : avec date d'échéance optionnelle

```
@ALITA souviens-toi que je préfère les résumés courts
@ALITA rappelle-moi d'appeler le médecin jeudi
```

---

## Configuration avancée

### Métriques hôte vs container (FEMTO)

Par défaut, FEMTO lit `/proc` pour obtenir les métriques de l'hôte (RAM, CPU, uptime). Pour la consommation disque de l'hôte, deux options :

**Option A** — Bind mount du système de fichiers hôte :
```yaml
# dans docker-compose.yml, service femto :
volumes:
  - /:/host:ro
```
Puis modifier `system_metrics.py` pour utiliser `df /host`.

**Option B** — Mode réseau hôte + PID hôte :
```yaml
network_mode: host
pid: host
```
(désactive l'isolation réseau — non recommandé en prod)

### Modifier le modèle LLM

```bash
# .env — modèle partagé (FEMTO + GIORGIO)
ASMO_OLLAMA_MODEL=llama3.1:8b

# Modèle spécifique à ALITA (override)
ALITA_OLLAMA_MODEL=mistral-nemo
```

Modèles recommandés avec tool calling : `mistral:7b`, `mistral-nemo`, `llama3.1:8b`, `qwen2.5:7b`

---

## Développement

### Tester localement sans Docker

```bash
# Installer la lib commons en éditable
pip install -e commons/

# Variables d'environnement pour dev
export FEMTO_DISCORD_TOKEN=xxx
export ASMO_OLLAMA_BASE_URL=http://localhost:11434
export ASMO_REDIS_URL=redis://localhost:6379
export ASMO_LOG_JSON=false

# Lancer FEMTO
cd femto && pip install -e . && python -m src.main

# Lancer ALITA
cd alita && pip install -e . && python -m src.main
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
- **Whitelist HA** : `call_ha_service` est limité à 7 domaines autorisés explicitement.
- **Secrets en env vars** : aucun secret en dur dans le code, tokens Spotify en SQLite chiffrée.
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
| Score moto toujours indisponible | Clé API météo absente | Vérifier `ALITA_WEATHER_API_KEY` |
| Spotify : "non connecté" | Auth OAuth non effectuée | Faire `!spotify-auth` et suivre le lien |
| Portfolio vide | JSON mal formé | Vérifier le format de `ALITA_PORTFOLIO` dans `.env` |
| HA non disponible | Token HA absent ou URL incorrecte | Vérifier `ALITA_HA_TOKEN` et `ALITA_HA_URL` |
| `ExecutorError: Command 'X' is not in the whitelist` | Commande non autorisée | Ajouter à `ALLOWED_COMMANDS` dans `executor.py` si légitime |

---

## Roadmap

- [x] FEMTO : monitoring système complet
- [x] FEMTO → ALITA : alertes Redis sur disque critique
- [x] GIORGIO : système de notation avec boutons Discord
- [x] GIORGIO → ALITA : publication des notations via Redis
- [x] ALITA : briefing matinal complet (météo, moto, bourse, HA, rappels, alertes)
- [x] ALITA : score moto intelligent (analyse 8h–19h, pluie rédhibitoire)
- [x] ALITA : intégration Home Assistant (états + contrôle)
- [x] ALITA : portefeuille boursier yfinance
- [x] ALITA : recherche web SearXNG
- [x] ALITA : contrôle Spotify avec OAuth2
- [x] ALITA : mémoire persistante SQLite (préférences + rappels)
- [ ] ALITA : intégration Google Calendar / Nextcloud CalDAV
- [ ] ALITA : résumé d'actualités via flux RSS
- [ ] GIORGIO : sync périodique du catalogue Jellyfin (`GIORGIO_SYNC_INTERVAL_HOURS`)
- [ ] GIORGIO : canal séparé pour les recommandations (`GIORGIO_RECOMMENDATION_CHANNEL_ID`)
- [ ] Dashboard web pour les métriques FEMTO (Prometheus + Grafana)
