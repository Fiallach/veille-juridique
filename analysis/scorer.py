"""
Module d'analyse IA — Scoring de pertinence via Claude API.
"""

import json
import logging
import hashlib
import os
from typing import Optional

import anthropic

from collectors.rss_collector import Article

logger = logging.getLogger(__name__)

# ── Modèle à utiliser ──
# On essaie plusieurs sources pour le nom du modèle
def _get_model():
    """Récupère le modèle à utiliser, avec fallback."""
    # 1. Variable d'environnement
    model = os.getenv("ANTHROPIC_MODEL", "")
    if model:
        return model
    # 2. Streamlit secrets
    try:
        import streamlit as st
        model = st.secrets.get("ANTHROPIC_MODEL", "")
        if model:
            return model
    except Exception:
        pass
    # 3. Config settings
    try:
        from config.settings import ANTHROPIC_MODEL
        if ANTHROPIC_MODEL:
            return ANTHROPIC_MODEL
    except Exception:
        pass
    # 4. Fallback sûr
    return "claude-sonnet-4-20250514"


# ── Seuil de pertinence ──
def _get_min_score():
    try:
        from config.settings import MIN_RELEVANCE_SCORE
        return MIN_RELEVANCE_SCORE
    except Exception:
        return 30


SCORING_SYSTEM_PROMPT = """Tu es un assistant juridique spécialisé en veille réglementaire.

Tu analyses des articles pour un juriste d'entreprise. Tu dois évaluer si l'article
est pertinent par rapport à AU MOINS UN des domaines d'expertise listés.

⚠️ RÈGLE CRITIQUE : Les domaines d'expertise sont ALTERNATIFS (logique OU).
Un article est pertinent dès qu'il touche UN SEUL des domaines listés.
Il n'est PAS nécessaire qu'il soit lié à tous les domaines à la fois.

Exemple : si les domaines sont "droit du tourisme, droit des marques, droit de la consommation",
un article sur la contrefaçon de marques est pertinent (→ droit des marques),
même s'il ne parle ni de tourisme ni de consommation.
Un article sur les pratiques commerciales trompeuses est pertinent (→ droit de la consommation).
Un article sur la propriété intellectuelle est pertinent (→ droit des marques).

Réponds UNIQUEMENT en JSON valide. Pas de markdown, pas de backticks, pas d'explication autour.

{
    "score": <entier de 0 à 100>,
    "domaine": "<le domaine d'expertise le plus pertinent>",
    "resume": "<résumé en 2-3 phrases, en français>",
    "tags": ["<tag1>", "<tag2>"],
    "action_level": "<information|vigilance|action_urgente>",
    "justification": "<1 phrase>"
}

Barème (par rapport au MEILLEUR domaine matché) :
- 85-100 : Impact direct — nouvelle loi, décision majeure, sanction dans le domaine
- 70-84 : À surveiller — projet de loi, recommandation, évolution jurisprudentielle
- 50-69 : Lien clair mais indirect — doctrine, article de fond, sujet connexe
- 30-49 : Lien ténu — culture juridique générale
- 0-29 : Non pertinent pour aucun domaine

Niveaux d'action :
- "action_urgente" : score ≥ 85
- "vigilance" : score 60-84
- "information" : score < 60

IMPORTANT : Sois INCLUSIF. En cas de doute, score plus haut.
Un juriste préfère recevoir un article moyennement pertinent que d'en rater un important."""


def build_scoring_prompt(article: Article, expertise_domains: str) -> str:
    """Construit le prompt de scoring."""
    content = article.content_extract[:2000] if article.content_extract else ""

    return f"""Domaines d'expertise du juriste (ALTERNATIFS — matcher AU MOINS UN suffit) :
{expertise_domains}

Article à évaluer :
- Titre : {article.title}
- Source : {article.source_name}
- Date : {article.published_date or "non disponible"}
- URL : {article.url}
- Contenu/Extrait :
{content if content else "(pas de contenu disponible, évaluer sur le titre)"}

Évalue la pertinence. Réponds UNIQUEMENT en JSON."""


def _parse_response(raw_text: str) -> dict:
    """Parse la réponse de Claude, gère les cas foireux."""
    text = raw_text.strip()

    # Retirer les backticks markdown
    if text.startswith("```"):
        text = text.split("\n", 1)[-1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
    if text.startswith("```json"):
        text = text[7:]

    text = text.strip()

    # Essayer de parser
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Chercher un objet JSON dans le texte
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError:
            pass

    return {}


def score_article(
    article: Article,
    expertise_domains: str,
    client: Optional[anthropic.Anthropic] = None,
) -> Article:
    """
    Évalue un article via Claude API et enrichit l'objet Article.
    """
    model = _get_model()

    if client is None:
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            try:
                import streamlit as st
                api_key = st.secrets.get("ANTHROPIC_API_KEY", "")
            except Exception:
                pass
        client = anthropic.Anthropic(api_key=api_key)

    prompt = build_scoring_prompt(article, expertise_domains)

    try:
        response = client.messages.create(
            model=model,
            max_tokens=500,
            system=SCORING_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text
        result = _parse_response(raw)

        if not result:
            logger.warning(f"Réponse non parsable pour '{article.title[:50]}': {raw[:200]}")
            article.relevance_score = 0
            article.summary = "Erreur: réponse IA non parsable"
            return article

        # Extraire les champs
        article.relevance_score = int(result.get("score", 0))
        article.summary = result.get("resume", result.get("résumé", ""))
        article.tags = result.get("tags", [])
        article.action_level = result.get("action_level", "information")

        # Ajouter le domaine matché au résumé
        domaine = result.get("domaine", result.get("domaine_matché", ""))
        if domaine and article.summary:
            article.summary = f"[{domaine}] {article.summary}"

        logger.info(
            f"Score {article.relevance_score} pour '{article.title[:50]}' "
            f"[{article.action_level}] domaine={domaine}"
        )

    except anthropic.APIStatusError as e:
        logger.error(f"Erreur API Anthropic (status): {e.status_code} - {e.message}")
        article.relevance_score = 0
        article.summary = f"Erreur API: {e.status_code}"
    except anthropic.APIConnectionError as e:
        logger.error(f"Erreur connexion API: {e}")
        article.relevance_score = 0
        article.summary = "Erreur: connexion API impossible"
    except Exception as e:
        logger.error(f"Erreur scoring '{article.title[:50]}': {type(e).__name__}: {e}")
        article.relevance_score = 0
        article.summary = f"Erreur: {type(e).__name__}"

    return article


def generate_article_uid(article: Article) -> str:
    """Génère un identifiant unique pour la déduplication."""
    raw = f"{article.title.lower().strip()}{article.url.strip()}"
    return hashlib.md5(raw.encode()).hexdigest()
