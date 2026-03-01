"""
Collecteur intelligent d'articles.

Stratégie automatique :
1. Tente de découvrir un flux RSS sur le site
2. Si RSS trouvé → parse le flux
3. Si pas de RSS → scrape les liens <a> de la page d'accueil
4. Retourne des objets Article dans les deux cas
"""

import logging
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from typing import Optional
from urllib.parse import urljoin, urlparse

import feedparser
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; veille-juridique/1.0)"}
REQUEST_TIMEOUT = 20


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
    action_level: str = "information"
    uid: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ══════════════════════════════════════════
# ÉTAPE 1 : Découverte automatique de RSS
# ══════════════════════════════════════════

def _try_parse_feed(url: str) -> Optional[feedparser.FeedParserDict]:
    """Tente de parser une URL comme flux RSS. Retourne le feed si valide, None sinon."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        if resp.status_code != 200:
            return None

        content_type = resp.headers.get("content-type", "").lower()

        # Si c'est du HTML pur, ce n'est pas un RSS
        if "html" in content_type and "xml" not in content_type:
            return None

        parsed = feedparser.parse(resp.text)

        # Vérifier qu'il y a vraiment des entrées
        if parsed.entries and len(parsed.entries) > 0:
            return parsed

        return None
    except Exception:
        return None


def discover_rss(url: str) -> Optional[str]:
    """
    Découvre automatiquement le flux RSS d'un site.
    Retourne l'URL du flux RSS trouvé, ou None.

    Stratégie :
    1. Chercher les balises <link type="application/rss+xml"> dans le HTML
    2. Tester les chemins classiques (/rss, /feed, /rss.xml, etc.)
    3. Tester l'URL elle-même comme flux RSS
    """

    base_url = url.rstrip("/")
    domain = urlparse(url).netloc

    logger.info(f"🔍 Recherche de flux RSS pour {domain}...")

    # ── 1. Chercher dans le HTML ──
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "lxml")

            for link in soup.find_all("link", type=True):
                link_type = link.get("type", "").lower()
                if "rss" in link_type or "atom" in link_type:
                    href = link.get("href", "")
                    if href:
                        feed_url = urljoin(url, href)
                        feed = _try_parse_feed(feed_url)
                        if feed:
                            logger.info(f"✅ RSS trouvé via HTML <link>: {feed_url} ({len(feed.entries)} entrées)")
                            return feed_url
    except Exception as e:
        logger.debug(f"Erreur accès HTML {url}: {e}")

    # ── 2. Tester les chemins classiques ──
    common_paths = [
        "/rss", "/rss.xml", "/feed", "/feed.xml", "/feed/",
        "/atom.xml", "/feeds/posts/default",
        "/index.php/feed", "/blog/feed",
        "/fr/rss.xml",  # CNIL, sites gov.fr
        "/rss/actualites.xml",  # sites institutionnels
        "/articles/backend.php",  # Village de la Justice
    ]

    for path in common_paths:
        test_url = base_url + path
        feed = _try_parse_feed(test_url)
        if feed:
            logger.info(f"✅ RSS trouvé via test de chemin: {test_url} ({len(feed.entries)} entrées)")
            return test_url

    # ── 3. Tester l'URL elle-même ──
    feed = _try_parse_feed(url)
    if feed:
        logger.info(f"✅ L'URL elle-même est un flux RSS: {url}")
        return url

    logger.info(f"❌ Aucun flux RSS trouvé pour {domain}, fallback vers scraping")
    return None


# ══════════════════════════════════════════
# ÉTAPE 2 : Collecte via RSS
# ══════════════════════════════════════════

def _collect_rss(feed_url: str, source_name: str, days_back: int) -> list[Article]:
    """Collecte les articles depuis un flux RSS validé."""
    articles = []
    cutoff = datetime.now() - timedelta(days=days_back)

    try:
        resp = requests.get(feed_url, headers=HEADERS, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        parsed = feedparser.parse(resp.text)

        for entry in parsed.entries:
            # Date
            pub_date = None
            for date_attr in ("published_parsed", "updated_parsed"):
                raw = getattr(entry, date_attr, None)
                if raw:
                    try:
                        pub_date = datetime(*raw[:6])
                    except Exception:
                        pass
                    break

            # Filtrer par date
            if pub_date and pub_date < cutoff:
                continue

            # Contenu
            content = ""
            if hasattr(entry, "content") and entry.content:
                content = entry.content[0].get("value", "")
            elif hasattr(entry, "summary"):
                content = entry.summary or ""

            if content:
                try:
                    soup = BeautifulSoup(content, "lxml")
                    content = soup.get_text(separator=" ", strip=True)
                except Exception:
                    pass

            articles.append(Article(
                title=entry.get("title", "Sans titre"),
                url=entry.get("link", ""),
                source_name=source_name,
                source_type="rss",
                published_date=pub_date.isoformat() if pub_date else None,
                content_extract=content[:2000],
                author=entry.get("author", ""),
            ))

    except Exception as e:
        logger.error(f"Erreur parsing RSS {feed_url}: {e}")

    return articles


# ══════════════════════════════════════════
# ÉTAPE 3 : Scraping fallback
# ══════════════════════════════════════════

def _collect_scrape(url: str, source_name: str, days_back: int) -> list[Article]:
    """
    Scrape les liens <a> de la page d'accueil pour extraire les articles.
    Filtre les liens internes qui ressemblent à des articles (pas des menus, footers, etc.)
    """
    articles = []
    domain = urlparse(url).netloc

    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        seen_urls = set()

        # Parcourir tous les liens
        for a_tag in soup.find_all("a", href=True):
            href = a_tag.get("href", "").strip()
            if not href:
                continue

            # Construire l'URL absolue
            full_url = urljoin(url, href)
            parsed_url = urlparse(full_url)

            # Filtrer : garder uniquement les liens du même domaine
            if domain not in parsed_url.netloc:
                continue

            # Filtrer : ignorer les ancres, les pages d'accueil, les URLs trop courtes
            path = parsed_url.path.rstrip("/")
            if not path or len(path) < 10:
                continue

            # Filtrer : ignorer les liens de navigation courants
            skip_patterns = [
                "/tag/", "/category/", "/author/", "/page/",
                "/login", "/register", "/contact", "/about",
                "/mentions-legales", "/politique-de-confidentialite",
                "/cgu", "/cgv", "/plan-du-site", "/sitemap",
                ".pdf", ".jpg", ".png", ".gif", ".zip",
                "/wp-content/", "/wp-admin/",
                "#", "javascript:", "mailto:",
            ]
            if any(skip in full_url.lower() for skip in skip_patterns):
                continue

            # Éviter les doublons
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)

            # Extraire le titre depuis le texte du lien
            title = a_tag.get_text(strip=True)
            if not title or len(title) < 15:
                continue

            # Ignorer les textes de navigation
            nav_texts = [
                "lire la suite", "en savoir plus", "voir plus",
                "accueil", "contact", "connexion", "inscription",
                "suivant", "précédent", "retour",
            ]
            if title.lower().strip() in nav_texts:
                continue

            articles.append(Article(
                title=title[:200],
                url=full_url,
                source_name=source_name,
                source_type="scrape",
                published_date=None,
                content_extract="",  # Pas de contenu en scraping léger
            ))

        # Limiter le nombre d'articles scrapés (les premiers sont souvent les plus récents)
        articles = articles[:30]

    except Exception as e:
        logger.error(f"Erreur scraping {url}: {e}")

    return articles


# ══════════════════════════════════════════
# FONCTION PRINCIPALE (interface publique)
# ══════════════════════════════════════════

def collect_from_rss(source_url: str, source_name: str = "", days_back: int = 7) -> list[Article]:
    """
    Collecte intelligente d'articles depuis une URL.

    1. Tente de trouver un flux RSS
    2. Si RSS trouvé → collecte via RSS
    3. Si pas de RSS → scrape la page d'accueil

    Args:
        source_url: URL du site (pas besoin que ce soit un RSS)
        source_name: Nom de la source
        days_back: Nombre de jours en arrière

    Returns:
        Liste d'objets Article
    """
    if not source_name:
        source_name = urlparse(source_url).netloc.replace("www.", "")

    # Étape 1 : chercher un RSS
    rss_url = discover_rss(source_url)

    if rss_url:
        # Étape 2a : collecte RSS
        articles = _collect_rss(rss_url, source_name, days_back)
        if articles:
            logger.info(f"📡 {source_name}: {len(articles)} articles via RSS")
            return articles
        else:
            logger.warning(f"RSS trouvé mais vide pour {source_name}, fallback scrape")

    # Étape 2b : fallback scraping
    articles = _collect_scrape(source_url, source_name, days_back)
    logger.info(f"🌐 {source_name}: {len(articles)} articles via scraping")
    return articles
