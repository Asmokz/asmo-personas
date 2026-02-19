# ASMO Personas

Trois bots Discord autonomes pour le homelab **ASMO-01**.

| Bot | Rôle | Statut |
|-----|------|--------|
| **FEMTO** | Monitoring système & Docker | ✅ Fonctionnel |
| **ALITA** | Briefing matinal & assistant | 🏗️ Squelette |
| **GIORGIO** | Médias & recommandations Jellyfin | 🏗️ Squelette |

## Architecture

```
asmo-personas/
├── commons/              # Lib partagée (OllamaClient, BaseBot, ToolRegistry…)
├── femto/                # Bot monitoring (complètement implémenté)
├── alita/                # Bot briefing (squelette à compléter)
├── giorgio/              # Bot média (squelette à compléter)
├── scripts/
│   └── init_redis.py
├── docker-compose.yml
└── .env.example
```

**Stack** : Python 3.11 · discord.py · Ollama (Mistral 7B) · Redis · Docker Compose

---

## Prérequis

- Docker + Docker Compose v2
- Ollama installé sur l'hôte avec `mistral:7b` pulled :
  ```bash
  ollama pull mistral:7b
  ```
- Trois applications Discord créées sur <https://discord.com/developers/applications>
  (un token par bot)

---

## Déploiement

### 1. Cloner et configurer

```bash
cd /home/asmo
git clone <repo> asmo-personas   # ou déplacer ce répertoire
cd asmo-personas
cp .env.example .env
nano .env   # remplir les tokens Discord et les IDs de canaux
```

### 2. Récupérer les Channel IDs Discord

Dans Discord : activer le **mode développeur** (Paramètres → Avancé), puis clic droit sur un canal → **Copier l'identifiant**.

### 3. Inviter les bots sur leurs serveurs

Pour chaque bot, dans le portail développeur :
- **OAuth2 → URL Generator** → Scopes : `bot`, `applications.commands`
- Permissions : `Send Messages`, `Read Message History`, `View Channels`
- Coller l'URL d'invitation et inviter le bot sur le serveur dédié

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

---

## Configuration avancée

### Métriques hôte vs container

Par défaut, FEMTO monte `/proc` en lecture seule pour obtenir les métriques de l'hôte (RAM, CPU, uptime). Pour voir la consommation disque de l'hôte, deux options :

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
# .env
ASMO_OLLAMA_MODEL=llama3.1:8b  # ou tout modèle Ollama supportant le tool calling
```

Models recommandés avec tool calling : `mistral:7b`, `llama3.1:8b`, `qwen2.5:7b`

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
cd femto
pip install -e .
python -m src.main
```

### Ajouter un outil à FEMTO

1. Implémenter la méthode dans la classe appropriée (`SystemMetrics`, `DockerStatus`, etc.)
2. L'enregistrer dans `FemtoBot._register_tools()` avec `@reg.register(...)`
3. Rebuildez l'image : `docker compose build femto`

### Structure d'un outil

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
    # Toujours async, retourne une str
    return await self.xxx.faire_quelque_chose(param1)
```

---

## Sécurité

- **Whitelist stricte** : seules les commandes listées dans `CommandExecutor.ALLOWED_COMMANDS` sont exécutables. Aucune exécution shell arbitraire (`shell=False` partout).
- **Read-only** : aucun outil ne modifie l'état du système.
- **Socket Docker en RO** : monté en `:ro` — impossible d'écrire dans le socket.
- **Secrets en env vars** : aucun secret en dur dans le code.
- **Timeout sur chaque commande** : configurable via `FEMTO_CMD_TIMEOUT`.

---

## Dépannage

| Symptôme | Cause probable | Solution |
|----------|---------------|----------|
| Bot ne répond pas | Token invalide ou intents manquants | Vérifier `FEMTO_DISCORD_TOKEN` et activer **Message Content Intent** dans le portail développeur |
| `OllamaError: Connection failed` | Ollama non démarré | `systemctl start ollama` sur l'hôte |
| `redis.exceptions.ConnectionError` | Redis non démarré | `docker compose up -d redis` |
| `ExecutorError: Command 'X' is not in the whitelist` | Commande non autorisée | Ajouter à `ALLOWED_COMMANDS` dans `executor.py` si légitime |
| Les métriques disque montrent le FS du container | `/proc` non monté | Vérifier le volume `/proc:/proc:ro` dans docker-compose.yml |

---

## Roadmap

- [ ] ALITA : intégration Google Calendar / Nextcloud CalDAV
- [ ] ALITA : résumé d'actualités (RSS)
- [ ] GIORGIO : webhooks Jellyfin (notification à l'ajout d'un contenu)
- [ ] Inter-persona : FEMTO → ALITA alerte si seuil critique dépassé
- [ ] Persistence MariaDB pour l'historique long terme
- [ ] Dashboard web minimaliste pour les métriques
