"""
Module d'analyse IA — Scoring de pertinence via Claude API.
Évalue chaque article collecté par rapport aux domaines d'expertise de l'utilisateur.
"""
import json
import logging
import hashlib
from typing import Optional

import anthropic

from collectors.rss_collector import Article
from config.settings import (
    ANTHROPIC_API_KEY, ANTHROPIC_MODEL,
    MIN_RELEVANCE_SCORE, ARTICLE_EXTRACT_MAX_CHARS
)

logger = logging.getLogger(__name__)


SCORING_SYSTEM_PROMPT = """Tu es un assistant juridique spécialisé en veille réglementaire.
Tu analyses des articles juridiques pour un juriste d'entreprise.

Tu dois évaluer la pertinence de chaque article par rapport aux domaines d'expertise fournis.

Réponds UNIQUEMENT en JSON valide, sans markdown, sans backticks, sans explication.
Le JSON doit avoir exactement cette structure :
{
  "score": <entier de 0 à 100>,
  "résumé": "<résumé en 2-3 phrases maximum, en français>",
  "tags": ["<tag1>", "<tag2>", "<tag3 max>"],
  "action_level": "<information|vigilance|action_urgente>",
  "justification": "<1 phrase expliquant le score>"
}

Critères de scoring :
- 90-100 : Impact direct et immédiat sur l'activité (nouvelle loi applicable, décision de justice majeure, mise en demeure sectorielle)
- 70-89 : Pertinent et à surveiller (projet de loi, recommandation d'autorité, évolution jurisprudentielle)
- 50-69 : Intéressant mais impact indirect (doctrine, article de fond, droit comparé)
- 30-49 : Faiblement lié aux domaines d'expertise
- 0-29 : Non pertinent

Critères pour action_level :
- "action_urgente" : nécessite une action ou une information immédiate (score ≥ 85)
- "vigilance" : à surveiller, évolution en cours (score 65-84)
- "information" : pour information, culture juridique (score < 65)"""


def build_scoring_prompt(article: Article, expertise_domains: str) -> str:
    """Construit le prompt de scoring pour un article donné."""
    content = article.content_extract[:ARTICLE_EXTRACT_MAX_CHARS]

    return f"""Domaines d'expertise du juriste :
{expertise_domains}

Article à évaluer :
- Titre : {article.title}
- Source : {article.source_name} ({article.source_type})
- Date : {article.published_date or "non disponible"}
- URL : {article.url}
- Contenu/Extrait :
{content if content else "(contenu non disponible, évaluer sur le titre uniquement)"}

Évalue la pertinence de cet article. Réponds en JSON uniquement."""


def score_article(
    article: Article,
    expertise_domains: str,
    client: Optional[anthropic.Anthropic] = None,
) -> Article:
    """
    Évalue un article via Claude API et enrichit l'objet Article.
    
    Args:
        article: Article à scorer
        expertise_domains: Description des domaines d'expertise
        client: Client Anthropic (créé si non fourni)
    
    Returns:
        L'article enrichi avec score, résumé, tags, action_level
    """
    if client is None:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    prompt = build_scoring_prompt(article, expertise_domains)

    try:
        response = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=500,
            system=SCORING_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        # Parser le JSON
        raw = response.content[0].text.strip()
        # Nettoyer d'éventuels backticks markdown
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]

        result = json.loads(raw)

        article.relevance_score = int(result.get("score", 0))
        article.summary = result.get("résumé", "")
        article.tags = result.get("tags", [])
        article.action_level = result.get("action_level", "information")

        logger.debug(
            f"Score {article.relevance_score} pour '{article.title[:60]}' "
            f"[{article.action_level}]"
        )

    except json.JSONDecodeError as e:
        logger.warning(f"Réponse IA non-JSON pour '{article.title[:50]}': {e}")
        article.relevance_score = 0
        article.summary = "Erreur d'analyse"
    except anthropic.APIError as e:
        logger.error(f"Erreur API Anthropic: {e}")
        article.relevance_score = 0
        article.summary = "Erreur API"
    except Exception as e:
        logger.error(f"Erreur scoring '{article.title[:50]}': {e}")
        article.relevance_score = 0

    return article


def score_articles_batch(
    articles: list[Article],
    expertise_domains: str,
) -> list[Article]:
    """
    Score un lot d'articles et retourne ceux au-dessus du seuil.
    
    Args:
        articles: Liste d'articles à scorer
        expertise_domains: Description des domaines d'expertise
    
    Returns:
        Liste d'articles scorés et filtrés (score ≥ MIN_RELEVANCE_SCORE),
        triés par score décroissant
    """
    if not ANTHROPIC_API_KEY:
        logger.error("ANTHROPIC_API_KEY non configurée !")
        return []

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    scored = []

    logger.info(f"Scoring de {len(articles)} articles via Claude API...")

    for i, article in enumerate(articles):
        logger.info(f"  [{i+1}/{len(articles)}] {article.title[:70]}...")
        scored_article = score_article(article, expertise_domains, client)

        # Générer un UID pour la déduplication
        scored_article.uid = generate_article_uid(scored_article)
        scored.append(scored_article)

    # Filtrer et trier
    relevant = [a for a in scored if a.relevance_score >= MIN_RELEVANCE_SCORE]
    relevant.sort(key=lambda a: a.relevance_score, reverse=True)

    logger.info(
        f"Scoring terminé : {len(relevant)}/{len(articles)} articles retenus "
        f"(seuil ≥ {MIN_RELEVANCE_SCORE})"
    )

    return relevant


def generate_article_uid(article: Article) -> str:
    """Génère un identifiant unique pour la déduplication."""
    raw = f"{article.title.lower().strip()}{article.url.strip()}"
    return hashlib.md5(raw.encode()).hexdigest()
