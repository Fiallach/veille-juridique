# 📋 Veille Juridique Automatisée

**Outil d'automatisation de la veille juridique** — Collecte, analyse IA et digest hebdomadaire par email.

## Architecture

```
veille-juridique/
├── app.py                  # Interface Streamlit (configuration)
├── main.py                 # Orchestrateur principal (lancement pipeline)
├── config/
│   ├── settings.py         # Configuration globale
│   └── user_config.json    # Profil utilisateur (généré par l'UI)
├── collectors/
│   ├── rss_collector.py    # Collecte flux RSS
│   ├── web_scraper.py      # Scraping sites publics/privés (Playwright)
│   └── email_parser.py     # Parsing newsletters (IMAP)
├── analysis/
│   ├── scorer.py           # Scoring IA via Claude API
│   └── dedup.py            # Déduplication des articles
├── email_sender/
│   └── sender.py           # Envoi du digest (SMTP / SendGrid)
├── templates/
│   └── digest.html         # Template HTML du digest email
├── data/
│   └── articles.db         # Base SQLite (historique)
├── requirements.txt
├── .env.example
└── README.md
```

## Installation

```bash
# 1. Cloner le projet
git clone <repo> && cd veille-juridique

# 2. Environnement virtuel
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows

# 3. Dépendances
pip install -r requirements.txt

# 4. Installer Playwright (navigateur headless)
playwright install chromium

# 5. Configurer les variables d'environnement
cp .env.example .env
# Éditer .env avec vos clés API
```

## Configuration

### Option 1 — Interface Streamlit
```bash
streamlit run app.py
```
Ouvre http://localhost:8501 et renseigne tes sources, domaines, credentials.

### Option 2 — Édition manuelle
Éditer directement `config/user_config.json`.

## Lancement

```bash
# Exécution unique (test)
python main.py

# Exécution planifiée (cron)
# Ajouter dans crontab -e :
# 0 7 * * 1 cd /path/to/veille-juridique && /path/to/venv/bin/python main.py
```

## Variables d'environnement (.env)

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Clé API Anthropic (Claude) |
| `SMTP_HOST` | Serveur SMTP (ex: smtp.office365.com) |
| `SMTP_PORT` | Port SMTP (587) |
| `SMTP_USER` | Email expéditeur |
| `SMTP_PASSWORD` | Mot de passe SMTP |
| `IMAP_HOST` | Serveur IMAP pour newsletters |
| `IMAP_USER` | Email de la boîte newsletters |
| `IMAP_PASSWORD` | Mot de passe IMAP |
| `ENCRYPTION_KEY` | Clé Fernet pour chiffrement credentials |
