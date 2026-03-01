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
    ANTHROPIC_API_KEY,
    ANTHROPIC_MODEL,
    MIN_RELEVANCE_SCORE,
    ARTICLE_EXTRACT_MAX_CHARS
)

logger = logging.getLogger(__name__)

SCORING_SYSTEM_PROMPT = """Tu es un assistant juridique spécialisé en veille réglementaire.

Tu analyses des articles pour un juriste d'entreprise. Tu dois évaluer si l'article
est pertinent par rapport à AU MOINS UN des domaines d'expertise listés.

⚠️ RÈGLE CRITIQUE : Les domaines d'expertise sont ALTERNATIFS (logique OU).
Un article est pertinent dès qu'il touche UN SEUL des domaines listés.
Il n'est PAS nécessaire qu'il soit lié à tous les domaines à la fois.

Exemple : si les domaines sont "droit du tourisme, droit des marques, droit de la consommation",
un article sur la contrefaçon de marques est pertinent (→ droit des marques),
même s'il ne parle ni de tourisme ni de consommation.

Réponds UNIQUEMENT en JSON valide, sans markdown, sans backticks, sans explication.

{
    "score": <entier de 0 à 100>,
    "domaine_matché": "<le domaine d'expertise le plus pertinent parmi ceux listés>",
    "résumé": "<résumé en 2-3 phrases, en français>",
    "tags": ["<tag1>", "<tag2>", "<tag3 max>"],
    "action_level": "<information|vigilance|action_urgente>",
    "justification": "<1 phrase expliquant pourquoi cet article est pertinent (ou non) pour le domaine matché>"
}

Critères de scoring (par rapport au MEILLEUR domaine matché) :
- 85-100 : Impact direct et immédiat — nouvelle loi, décision majeure, mise en demeure dans le domaine
- 70-84 : Pertinent et à surveiller — projet de loi, recommandation d'autorité, évolution jurisprudentielle
- 50-69 : Lien clair mais indirect — doctrine, article de fond, droit comparé, sujet connexe
- 30-49 : Lien ténu — touche le domaine de loin, culture juridique générale utile
- 0-29 : Non pertinent pour aucun des domaines listés

Critères pour action_level :
- "action_urgente" : action ou information immédiate nécessaire (score ≥ 85)
- "vigilance" : à surveiller, évolution en cours (score 60-84)
- "information" : pour information, culture juridique (score < 60)

IMPORTANT : Sois INCLUSIF dans ton scoring. En cas de doute, score plus haut plutôt que plus bas.
Un juriste préfère recevoir un article moyennement pertinent que de rater un article important."""


def build_scoring_prompt(article: Article, expertise_domains: str) -> str:
    """Construit le prompt de scoring pour un article donné."""
    content = article.content_extract[:ARTICLE_EXTRACT_MAX_CHARS]

    return f"""Domaines d'expertise du juriste (ALTERNATIFS — l'article doit matcher AU MOINS UN) :
{expertise_domains}

Article à évaluer :
- Titre : {article.title}
- Source : {article.source_name} ({article.source_type})
- Date : {article.published_date or "non disponible"}
- URL : {article.url}
- Contenu/Extrait :
{content if content else "(contenu non disponible, évaluer sur le titre uniquement)"}

Évalue la pertinence de cet article par rapport à au moins un des domaines ci-dessus.
Réponds en JSON uniquement."""


def score_article(
    article: Article,
    expertise_domains: str,
    client: Optional[anthropic.Anthropic] = None,
) -> Article:
    """
    Évalue un article via Claude API et enrichit l'objet Article.
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

        raw = response.content[0].text.strip()

        # Nettoyer d'éventuels backticks markdown
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]

        result = json.loads(raw)

        article.relevance_score = int(result.get("score", 0))
        article.summary = result.get("résumé", "")
        article.tags = result.get("tags", [])
        article.action_level = result.get("action_level", "information")

        # Ajouter le domaine matché dans le résumé si disponible
        domaine = result.get("domaine_matché", "")
        if domaine and article.summary:
            article.summary = f"[{domaine}] {article.summary}"

        logger.debug(
            f"Score {article.relevance_score} pour '{article.title[:60]}' "
            f"[{article.action_level}] domaine={domaine}"
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
        scored_article.uid = generate_article_uid(scored_article)
        scored.append(scored_article)

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
