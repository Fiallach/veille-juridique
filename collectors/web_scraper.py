"""
Scraper web avec Playwright pour les sites publics et privés.
Gère l'authentification automatique pour les sites nécessitant un login.
"""
import logging
import asyncio
from typing import Optional
from datetime import datetime

from playwright.async_api import async_playwright, Page, Browser
from bs4 import BeautifulSoup

from collectors.rss_collector import Article
from config.settings import decrypt_value

logger = logging.getLogger(__name__)


# === Stratégies de login par site ===
# Chaque site privé a sa propre logique d'authentification.
# On définit ici les sélecteurs CSS pour chaque plateforme connue.

LOGIN_STRATEGIES = {
    "lexis360.fr": {
        "login_url": "https://www.lexis360.fr/Auth/Login",
        "username_selector": "#Username",
        "password_selector": "#Password",
        "submit_selector": "button[type='submit']",
        "success_indicator": ".user-menu",  # élément visible après login
    },
    "lamyline.lamy.fr": {
        "login_url": "https://lamyline.lamy.fr/Content/Login.aspx",
        "username_selector": "#txtLogin",
        "password_selector": "#txtPassword",
        "submit_selector": "#btnConnect",
        "success_indicator": ".user-info",
    },
    "dalloz.fr": {
        "login_url": "https://www.dalloz.fr/login",
        "username_selector": "#email",
        "password_selector": "#password",
        "submit_selector": "button[type='submit']",
        "success_indicator": ".user-account",
    },
    # Ajouter d'autres sites ici...
}


# === Sélecteurs de contenu par site ===
# Définit quels éléments HTML contiennent les articles sur chaque site.

CONTENT_SELECTORS = {
    "default": {
        "article_list": "article, .article, .post, .entry, .news-item",
        "title": "h1, h2, h3, .title, .headline",
        "link": "a",
        "date": "time, .date, .published, .post-date",
        "excerpt": "p, .excerpt, .summary, .description",
    },
    "legifrance.gouv.fr": {
        "article_list": ".result-item, .article-item",
        "title": "h3 a, .title a",
        "link": "a",
        "date": ".date",
        "excerpt": ".description",
    },
    "dalloz-actualite.fr": {
        "article_list": ".node-article, .article-teaser",
        "title": "h2 a, .field-title a",
        "link": "a",
        "date": ".field-date, time",
        "excerpt": ".field-body p, .field-chapo",
    },
    "lexis360.fr": {
        "article_list": ".search-result, .document-item",
        "title": "h3 a, .doc-title a",
        "link": "a",
        "date": ".doc-date",
        "excerpt": ".doc-excerpt",
    },
}


def get_selectors(url: str) -> dict:
    """Retourne les sélecteurs appropriés pour un site donné."""
    for domain, selectors in CONTENT_SELECTORS.items():
        if domain in url:
            return selectors
    return CONTENT_SELECTORS["default"]


async def login_to_site(page: Page, site_config: dict,
                        username: str, password: str) -> bool:
    """
    Effectue le login sur un site privé.
    
    Args:
        page: Page Playwright
        site_config: Configuration du site (sélecteurs login)
        username: Nom d'utilisateur
        password: Mot de passe
    
    Returns:
        True si le login a réussi
    """
    try:
        await page.goto(site_config["login_url"], wait_until="networkidle")
        await page.fill(site_config["username_selector"], username)
        await page.fill(site_config["password_selector"], password)
        await page.click(site_config["submit_selector"])
        await page.wait_for_load_state("networkidle")

        # Vérifier le succès
        try:
            await page.wait_for_selector(
                site_config["success_indicator"], timeout=10000
            )
            logger.info(f"Login réussi sur {site_config['login_url']}")
            return True
        except Exception:
            logger.warning(f"Login potentiellement échoué sur {site_config['login_url']}")
            return False

    except Exception as e:
        logger.error(f"Erreur de login: {e}")
        return False


async def scrape_page(page: Page, url: str,
                      source_name: str) -> list[Article]:
    """
    Scrape une page web pour en extraire les articles.
    
    Args:
        page: Page Playwright (déjà authentifiée si nécessaire)
        url: URL de la page à scraper
        source_name: Nom de la source
    
    Returns:
        Liste d'objets Article
    """
    articles = []
    selectors = get_selectors(url)

    try:
        await page.goto(url, wait_until="networkidle", timeout=30000)
        content = await page.content()
        soup = BeautifulSoup(content, "lxml")

        # Trouver les blocs articles
        article_elements = soup.select(selectors["article_list"])

        if not article_elements:
            # Fallback : chercher tous les liens avec un titre
            logger.info(f"Aucun article trouvé avec les sélecteurs standard sur {url}. Fallback.")
            article_elements = soup.find_all(["article", "div"], class_=True)

        for elem in article_elements[:30]:  # Limiter à 30 articles
            try:
                # Titre
                title_elem = elem.select_one(selectors["title"])
                if not title_elem:
                    continue
                title = title_elem.get_text(strip=True)
                if not title or len(title) < 10:
                    continue

                # Lien
                link_elem = title_elem if title_elem.name == "a" else title_elem.find("a")
                if not link_elem:
                    link_elem = elem.select_one(selectors["link"])
                article_url = link_elem.get("href", "") if link_elem else ""
                if article_url and article_url.startswith("/"):
                    base = url.split("//")[0] + "//" + url.split("//")[1].split("/")[0]
                    article_url = base + article_url

                # Date
                date_elem = elem.select_one(selectors["date"])
                pub_date = date_elem.get_text(strip=True) if date_elem else None

                # Extrait
                excerpt_elem = elem.select_one(selectors["excerpt"])
                excerpt = excerpt_elem.get_text(strip=True) if excerpt_elem else ""

                article = Article(
                    title=title,
                    url=article_url,
                    source_name=source_name,
                    source_type="scrape",
                    published_date=pub_date,
                    content_extract=excerpt[:2000],
                )
                articles.append(article)

            except Exception as e:
                logger.debug(f"Erreur parsing article: {e}")
                continue

    except Exception as e:
        logger.error(f"Erreur scraping {url}: {e}")

    logger.info(f"Scrape {source_name}: {len(articles)} articles trouvés")
    return articles


async def scrape_article_content(page: Page, url: str,
                                 max_chars: int = 2000) -> str:
    """
    Récupère le contenu complet d'un article individuel.
    Utilisé pour enrichir l'extrait avant l'analyse IA.
    """
    try:
        await page.goto(url, wait_until="networkidle", timeout=20000)
        content = await page.content()
        soup = BeautifulSoup(content, "lxml")

        # Supprimer les éléments non pertinents
        for tag in soup.find_all(["nav", "header", "footer", "aside", "script",
                                   "style", "iframe", "form"]):
            tag.decompose()

        # Chercher le contenu principal
        main = (soup.find("main") or soup.find("article") or
                soup.find(class_=["content", "article-body", "post-content"]))

        if main:
            text = main.get_text(separator="\n", strip=True)
        else:
            text = soup.get_text(separator="\n", strip=True)

        return text[:max_chars]

    except Exception as e:
        logger.debug(f"Impossible de récupérer le contenu de {url}: {e}")
        return ""


async def collect_from_website(
    url: str,
    source_name: str = "",
    credentials: Optional[dict] = None,
    pages_to_scrape: Optional[list[str]] = None,
) -> list[Article]:
    """
    Point d'entrée principal : scrape un site (public ou privé).
    
    Args:
        url: URL du site
        source_name: Nom affiché de la source
        credentials: {"username": "...", "password_encrypted": "..."} si site privé
        pages_to_scrape: Liste d'URLs spécifiques à scraper (optionnel)
    
    Returns:
        Liste d'objets Article
    """
    if not source_name:
        source_name = url.split("//")[-1].split("/")[0]

    all_articles = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        try:
            # Login si credentials fournis
            if credentials:
                domain = url.split("//")[-1].split("/")[0]
                strategy = None
                for known_domain, config in LOGIN_STRATEGIES.items():
                    if known_domain in domain:
                        strategy = config
                        break

                if strategy:
                    password = decrypt_value(credentials["password_encrypted"])
                    logged_in = await login_to_site(
                        page, strategy, credentials["username"], password
                    )
                    if not logged_in:
                        logger.error(f"Échec login sur {source_name}, skip.")
                        return []
                else:
                    logger.warning(
                        f"Aucune stratégie de login connue pour {domain}. "
                        f"Tentative sans authentification."
                    )

            # Scraper les pages
            urls_to_scrape = pages_to_scrape or [url]
            for page_url in urls_to_scrape:
                articles = await scrape_page(page, page_url, source_name)
                all_articles.extend(articles)

            # Enrichir les articles avec le contenu complet (top 10)
            for article in all_articles[:10]:
                if article.url and len(article.content_extract) < 200:
                    full_content = await scrape_article_content(
                        page, article.url
                    )
                    if full_content:
                        article.content_extract = full_content

        finally:
            await browser.close()

    return all_articles


def collect_from_website_sync(
    url: str,
    source_name: str = "",
    credentials: Optional[dict] = None,
    pages_to_scrape: Optional[list[str]] = None,
) -> list[Article]:
    """Version synchrone du collecteur (wrapper asyncio)."""
    return asyncio.run(
        collect_from_website(url, source_name, credentials, pages_to_scrape)
    )
