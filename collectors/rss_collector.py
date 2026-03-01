"""
Collecteur de flux RSS/Atom.
Gère les sources publiques qui exposent un flux RSS.
"""
import logging
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from typing import Optional

import feedparser
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


@dataclass
class Article:
    """Représente un article collecté, quelle que soit la source."""
    title: str
    url: str
    source_name: str
    source_type: str  # "rss", "scrape", "newsletter"
    published_date: Optional[str] = None
    content_extract: str = ""
    author: str = ""
    # Champs remplis par l'analyse IA
    relevance_score: int = 0
    summary: str = ""
    tags: list = field(default_factory=list)
    action_level: str = "information"  # information | vigilance | action_urgente
    uid: str = ""  # hash pour déduplication

    def to_dict(self) -> dict:
        return asdict(self)


# === Sources RSS connues avec leurs flux ===
KNOWN_RSS_FEEDS = {
    "legifrance.gouv.fr": [
        "https://www.legifrance.gouv.fr/eli/jo/rss",
    ],
    "eur-lex.europa.eu": [
        "https://eur-lex.europa.eu/EN/display-feed.html?type=ojc&format=rss",
    ],
    "dalloz-actualite.fr": [
        "https://www.dalloz-actualite.fr/rss.xml",
    ],
    "village-justice.com": [
        "https://www.village-justice.com/articles/backend.php",
    ],
    "cnil.fr": [
        "https://www.cnil.fr/fr/rss.xml",
    ],
}


def discover_rss_feed(url: str) -> list[str]:
    """
    Tente de découvrir automatiquement les flux RSS d'un site.
    Cherche dans le HTML les balises <link type="application/rss+xml">.
    """
    feeds = []

    # Vérifier d'abord les flux connus
    for domain, known_feeds in KNOWN_RSS_FEEDS.items():
        if domain in url:
            return known_feeds

    # Découverte automatique via le HTML
    try:
        headers = {"User-Agent": "Mozilla/5.0 (veille-juridique-bot)"}
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        # Chercher les balises link RSS/Atom
        for link in soup.find_all("link", type=True):
            if "rss" in link.get("type", "") or "atom" in link.get("type", ""):
                href = link.get("href", "")
                if href:
                    if href.startswith("/"):
                        href = url.rstrip("/") + href
                    feeds.append(href)

        # Tester les URLs classiques
        common_paths = ["/rss", "/rss.xml", "/feed", "/feed.xml", "/atom.xml"]
        for path in common_paths:
            test_url = url.rstrip("/") + path
            try:
                r = requests.head(test_url, headers=headers, timeout=5)
                if r.status_code == 200 and "xml" in r.headers.get("content-type", ""):
                    feeds.append(test_url)
            except Exception:
                pass

    except Exception as e:
        logger.warning(f"Impossible de découvrir RSS pour {url}: {e}")

    return feeds


def collect_from_rss(source_url: str, source_name: str = "",
                     days_back: int = 7) -> list[Article]:
    """
    Collecte les articles d'un flux RSS publié dans les N derniers jours.
    
    Args:
        source_url: URL du site ou du flux RSS directement
        source_name: Nom de la source (pour affichage)
        days_back: Nombre de jours en arrière à collecter
    
    Returns:
        Liste d'objets Article
    """
    articles = []
    cutoff = datetime.now() - timedelta(days=days_back)

    if not source_name:
        source_name = source_url.split("//")[-1].split("/")[0]

    # Trouver les flux RSS
    feeds = discover_rss_feed(source_url)
    if not feeds:
        # Essayer l'URL directement comme flux RSS
        feeds = [source_url]

    for feed_url in feeds:
        try:
            logger.info(f"Parsing RSS: {feed_url}")
            parsed = feedparser.parse(feed_url)

            if parsed.bozo and not parsed.entries:
                logger.warning(f"Flux RSS invalide ou vide: {feed_url}")
                continue

            for entry in parsed.entries:
                # Filtrer par date
                pub_date = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    pub_date = datetime(*entry.published_parsed[:6])
                elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
                    pub_date = datetime(*entry.updated_parsed[:6])

                if pub_date and pub_date < cutoff:
                    continue

                # Extraire le contenu
                content = ""
                if hasattr(entry, "content") and entry.content:
                    content = entry.content[0].get("value", "")
                elif hasattr(entry, "summary"):
                    content = entry.summary or ""

                # Nettoyer le HTML du contenu
                if content:
                    soup = BeautifulSoup(content, "lxml")
                    content = soup.get_text(separator=" ", strip=True)

                article = Article(
                    title=entry.get("title", "Sans titre"),
                    url=entry.get("link", ""),
                    source_name=source_name,
                    source_type="rss",
                    published_date=pub_date.isoformat() if pub_date else None,
                    content_extract=content[:2000],
                    author=entry.get("author", ""),
                )
                articles.append(article)

        except Exception as e:
            logger.error(f"Erreur lors du parsing RSS {feed_url}: {e}")

    logger.info(f"RSS {source_name}: {len(articles)} articles collectés")
    return articles
