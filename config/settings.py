"""
Configuration globale de l'application de veille juridique.
"""
import os
import json
from pathlib import Path
from dotenv import load_dotenv
from cryptography.fernet import Fernet

load_dotenv()

# === Chemins ===
BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data"
TEMPLATES_DIR = BASE_DIR / "templates"
USER_CONFIG_PATH = CONFIG_DIR / "user_config.json"
DB_PATH = DATA_DIR / "articles.db"

# === API ===
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = "claude-sonnet-4-20250514"

# === SMTP ===
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.office365.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")

# === IMAP ===
IMAP_HOST = os.getenv("IMAP_HOST", "outlook.office365.com")
IMAP_USER = os.getenv("IMAP_USER", "")
IMAP_PASSWORD = os.getenv("IMAP_PASSWORD", "")

# === Chiffrement ===
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY", "")

# === Scoring ===
MIN_RELEVANCE_SCORE = 60
MAX_ARTICLES_PER_DIGEST = 25
ARTICLE_EXTRACT_MAX_CHARS = 2000

# === Scheduling ===
DIGEST_DAY = "monday"
DIGEST_HOUR = 7
DIGEST_MINUTE = 0


def get_fernet():
    """Retourne une instance Fernet pour chiffrer/déchiffrer les credentials."""
    if not ENCRYPTION_KEY:
        raise ValueError("ENCRYPTION_KEY non définie dans .env")
    return Fernet(ENCRYPTION_KEY.encode())


def encrypt_value(value: str) -> str:
    """Chiffre une valeur sensible."""
    f = get_fernet()
    return f.encrypt(value.encode()).decode()


def decrypt_value(encrypted: str) -> str:
    """Déchiffre une valeur sensible."""
    f = get_fernet()
    return f.decrypt(encrypted.encode()).decode()


def load_user_config() -> dict:
    """Charge la configuration utilisateur depuis le fichier JSON."""
    if not USER_CONFIG_PATH.exists():
        return {
            "expertise_domains": "",
            "recipient_email": "",
            "public_sources": [],
            "private_sources": [],
            "newsletter_enabled": False,
            "frequency": "weekly",
        }
    with open(USER_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_user_config(config: dict):
    """Sauvegarde la configuration utilisateur."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(USER_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
