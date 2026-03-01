"""
Module de déduplication des articles.
Évite les doublons quand un même sujet est couvert par plusieurs sources.
"""
import logging
import re
from difflib import SequenceMatcher

from collectors.rss_collector import Article

logger = logging.getLogger(__name__)


def normalize_title(title: str) -> str:
    """Normalise un titre pour la comparaison."""
    title = title.lower().strip()
    title = re.sub(r"[^\w\s]", "", title)
    title = re.sub(r"\s+", " ", title)
    return title


def titles_similar(title1: str, title2: str, threshold: float = 0.65) -> bool:
    """Vérifie si deux titres sont similaires (ratio de séquence)."""
    n1 = normalize_title(title1)
    n2 = normalize_title(title2)
    return SequenceMatcher(None, n1, n2).ratio() >= threshold


def urls_same_article(url1: str, url2: str) -> bool:
    """Vérifie si deux URLs pointent vers le même article."""
    # Nettoyer les paramètres de tracking
    def clean(url):
        url = re.sub(r"[?&](utm_\w+|fbclid|gclid|ref)=[^&]*", "", url)
        return url.rstrip("/&?").lower()
    return clean(url1) == clean(url2)


def deduplicate_articles(articles: list[Article]) -> list[Article]:
    """
    Supprime les doublons en gardant l'article avec le meilleur score.
    
    Critères de doublon :
    1. Même URL (nettoyée)
    2. Titres très similaires (SequenceMatcher ≥ 0.65)
    
    Returns:
        Liste dédupliquée, triée par score décroissant
    """
    if not articles:
        return []

    # Trier par score décroissant (on garde le meilleur en cas de doublon)
    sorted_articles = sorted(articles, key=lambda a: a.relevance_score, reverse=True)
    unique = []

    for article in sorted_articles:
        is_duplicate = False
        for existing in unique:
            # Check URL
            if article.url and existing.url:
                if urls_same_article(article.url, existing.url):
                    is_duplicate = True
                    break
            # Check titre
            if titles_similar(article.title, existing.title):
                is_duplicate = True
                # Fusionner les tags
                existing.tags = list(set(existing.tags + article.tags))
                break

        if not is_duplicate:
            unique.append(article)

    removed = len(articles) - len(unique)
    if removed:
        logger.info(f"Déduplication : {removed} doublons supprimés ({len(unique)} articles restants)")

    return unique
