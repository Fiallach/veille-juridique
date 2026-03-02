"""
Module d'analyse IA — Scoring via Google Gemini API.

Pipeline optimisé :
1. generate_keywords() — 1 appel API → mots-clés depuis les domaines
2. prefilter_articles() — 0 appel → filtre local
3. score_batch() — 2-3 appels API → scoring par lots de 10
"""

import json
import logging
import hashlib
from typing import Optional

from google import genai
from google.genai import types

from collectors.rss_collector import Article

logger = logging.getLogger(__name__)

GEMINI_MODEL = "gemini-2.0-flash"


# ══════════════════════════════════════════
# CLIENT
# ══════════════════════════════════════════

def get_gemini_client(api_key: str) -> genai.Client:
    """Crée un client Gemini."""
    return genai.Client(api_key=api_key)


# ══════════════════════════════════════════
# ÉTAPE 1 : Génération de mots-clés (1 appel)
# ══════════════════════════════════════════

KEYWORDS_SYSTEM = """Tu es un assistant juridique expert.
On te donne les domaines d'expertise d'un juriste.
Génère une liste exhaustive de mots-clés et expressions pour filtrer des articles juridiques pertinents.

Inclus :
- Termes juridiques exacts (ex: "pratiques commerciales trompeuses")
- Synonymes et variantes (ex: "PCD", "publicité mensongère")
- Institutions (ex: "DGCCRF", "CNIL", "INPI")
- Codes et lois (ex: "Code du tourisme", "L.121-1")
- Termes connexes (ex: pour "droit des marques" → "contrefaçon", "brevet", "PI")
- Termes anglais courants (ex: "green claims", "co-branding")

Réponds UNIQUEMENT avec un JSON array de strings. Pas de markdown, pas de backticks.
Génère entre 40 et 80 mots-clés. Sois EXHAUSTIF."""


def generate_keywords(expertise_domains: str, client: genai.Client) -> list[str]:
    """Génère des mots-clés depuis les domaines d'expertise. 1 appel API."""
    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            config=types.GenerateContentConfig(
                system_instruction=KEYWORDS_SYSTEM,
                max_output_tokens=1500,
                temperature=0.3,
            ),
            contents=f"Domaines d'expertise :\n{expertise_domains}\n\nGénère la liste de mots-clés.",
        )

        raw = response.text.strip()

        # Nettoyer backticks
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw.rsplit("```", 1)[0]
        if raw.startswith("```json"):
            raw = raw[7:]
        raw = raw.strip()

        keywords = json.loads(raw)
        if isinstance(keywords, list):
            return [k.lower().strip() for k in keywords if isinstance(k, str) and len(k) > 1]

    except json.JSONDecodeError as e:
        logger.error(f"Erreur JSON mots-clés: {e}")
    except Exception as e:
        logger.error(f"Erreur génération mots-clés: {type(e).__name__}: {e}")

    return []


# ══════════════════════════════════════════
# ÉTAPE 2 : Pré-filtrage local (0 appel)
# ══════════════════════════════════════════

def prefilter_articles(articles: list[Article], keywords: list[str]) -> tuple[list[Article], list[Article]]:
    """Filtre localement par mots-clés. Retourne (candidats, rejetés)."""
    if not keywords:
        return articles, []

    candidates = []
    rejected = []

    for article in articles:
        search_text = f"{article.title} {article.content_extract}".lower()
        matched = any(kw in search_text for kw in keywords)
        if matched:
            candidates.append(article)
        else:
            rejected.append(article)

    return candidates, rejected


# ══════════════════════════════════════════
# ÉTAPE 3 : Scoring par batch (2-3 appels)
# ══════════════════════════════════════════

BATCH_SCORING_SYSTEM = """Tu es un assistant juridique spécialisé en veille réglementaire.

Tu reçois une LISTE d'articles à évaluer pour un juriste.
Pour CHAQUE article, évalue s'il est pertinent par rapport à AU MOINS UN des domaines d'expertise.

⚠️ Les domaines sont ALTERNATIFS (logique OU). Un article pertinent pour UN SEUL domaine suffit.

Réponds UNIQUEMENT avec un JSON array. Pas de markdown, pas de backticks.
Chaque élément correspond à un article dans l'ordre :

[
    {
        "id": 0,
        "score": <0-100>,
        "domaine": "<domaine le plus pertinent>",
        "resume": "<résumé 1-2 phrases en français>",
        "tags": ["tag1", "tag2"],
        "action_level": "<information|vigilance|action_urgente>"
    }
]

Barème :
- 85-100 : Impact direct — nouvelle loi, décision majeure, sanction
- 70-84 : À surveiller — projet de loi, recommandation, jurisprudence
- 50-69 : Lien indirect — doctrine, article de fond
- 30-49 : Lien ténu — culture juridique
- 0-29 : Non pertinent

action_level : "action_urgente" si ≥85, "vigilance" si 60-84, "information" si <60

Sois INCLUSIF. En cas de doute, score plus haut."""


def _parse_json_response(raw: str) -> list:
    """Parse une réponse JSON, gère les cas foireux."""
    text = raw.strip()

    if text.startswith("```"):
        text = text.split("\n", 1)[-1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
    if text.startswith("```json"):
        text = text[7:]
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Chercher un array JSON
    start = text.find("[")
    end = text.rfind("]") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError:
            pass

    return []


def score_batch(
    articles: list[Article],
    expertise_domains: str,
    client: genai.Client,
    batch_size: int = 10,
) -> list[Article]:
    """Score par batch. Chaque batch = 1 appel API."""
    if not articles:
        return []

    scored = []

    for batch_start in range(0, len(articles), batch_size):
        batch = articles[batch_start:batch_start + batch_size]
        batch_num = batch_start // batch_size + 1

        # Construire le prompt
        articles_text = ""
        for i, article in enumerate(batch):
            content = article.content_extract[:800] if article.content_extract else "(titre uniquement)"
            articles_text += f"""
--- Article {i} ---
Titre : {article.title}
Source : {article.source_name}
Date : {article.published_date or "N/A"}
Contenu : {content}
"""

        prompt = f"""Domaines d'expertise (ALTERNATIFS) :
{expertise_domains}

{len(batch)} articles à évaluer :
{articles_text}

Réponds avec un JSON array de {len(batch)} éléments."""

        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                config=types.GenerateContentConfig(
                    system_instruction=BATCH_SCORING_SYSTEM,
                    max_output_tokens=3000,
                    temperature=0.2,
                ),
                contents=prompt,
            )

            results = _parse_json_response(response.text)

            if isinstance(results, list) and len(results) > 0:
                for i, article in enumerate(batch):
                    if i < len(results):
                        r = results[i]
                        article.relevance_score = int(r.get("score", 0))
                        article.summary = r.get("resume", r.get("résumé", ""))
                        article.tags = r.get("tags", [])
                        article.action_level = r.get("action_level", "information")

                        domaine = r.get("domaine", "")
                        if domaine and article.summary:
                            article.summary = f"[{domaine}] {article.summary}"
                    else:
                        article.relevance_score = 0
                        article.summary = "Non évalué (batch incomplet)"

                    article.uid = generate_article_uid(article)
                    scored.append(article)
            else:
                logger.warning(f"Réponse batch {batch_num} vide ou invalide")
                for article in batch:
                    article.relevance_score = 0
                    article.summary = "Erreur: réponse batch invalide"
                    article.uid = generate_article_uid(article)
                    scored.append(article)

        except Exception as e:
            logger.error(f"Erreur batch {batch_num}: {type(e).__name__}: {e}")
            for article in batch:
                article.relevance_score = 0
                article.summary = f"Erreur: {type(e).__name__}"
                article.uid = generate_article_uid(article)
                scored.append(article)

    return scored


# ══════════════════════════════════════════
# UTILITAIRES
# ══════════════════════════════════════════

def generate_article_uid(article: Article) -> str:
    """Identifiant unique pour déduplication."""
    raw = f"{article.title.lower().strip()}{article.url.strip()}"
    return hashlib.md5(raw.encode()).hexdigest()
