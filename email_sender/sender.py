"""
Module d'envoi du digest hebdomadaire par email.
Supporte SMTP (Office365, Gmail, etc.) et SendGrid.
"""
import logging
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from collectors.rss_collector import Article
from config.settings import (
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD,
    TEMPLATES_DIR, MIN_RELEVANCE_SCORE
)

logger = logging.getLogger(__name__)


def render_digest_html(
    articles: list[Article],
    total_sources: int = 0,
) -> str:
    """
    Génère le HTML du digest à partir du template Jinja2.
    
    Args:
        articles: Liste d'articles scorés et triés
        total_sources: Nombre total de sources analysées
    
    Returns:
        HTML du digest complet
    """
    # Classer les articles par niveau d'action
    urgent = [a for a in articles if a.action_level == "action_urgente"]
    vigilance = [a for a in articles if a.action_level == "vigilance"]
    info = [a for a in articles if a.action_level == "information"]

    # Charger et rendre le template
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=True,
    )
    template = env.get_template("digest.html")

    html = template.render(
        week_date=datetime.now().strftime("%d/%m/%Y"),
        total_articles=len(articles),
        urgent_count=len(urgent),
        vigilance_count=len(vigilance),
        info_count=len(info),
        urgent_articles=urgent,
        vigilance_articles=vigilance,
        info_articles=info,
        total_sources=total_sources,
        min_score=MIN_RELEVANCE_SCORE,
    )

    return html


def send_digest_email(
    recipient: str,
    articles: list[Article],
    total_sources: int = 0,
    smtp_host: str = None,
    smtp_port: int = None,
    smtp_user: str = None,
    smtp_password: str = None,
) -> bool:
    """
    Envoie le digest hebdomadaire par email.
    
    Args:
        recipient: Adresse email du destinataire
        articles: Liste d'articles à inclure dans le digest
        total_sources: Nombre de sources analysées
        smtp_*: Override des paramètres SMTP (optionnel)
    
    Returns:
        True si l'envoi a réussi
    """
    host = smtp_host or SMTP_HOST
    port = smtp_port or SMTP_PORT
    user = smtp_user or SMTP_USER
    password = smtp_password or SMTP_PASSWORD

    if not all([host, user, password, recipient]):
        logger.error("Configuration SMTP incomplète.")
        return False

    # Générer le HTML
    html_content = render_digest_html(articles, total_sources)

    # Construire l'email
    urgent_count = sum(1 for a in articles if a.action_level == "action_urgente")
    week = datetime.now().strftime("%d/%m/%Y")

    subject = f"📋 Veille Juridique — Semaine du {week}"
    if urgent_count > 0:
        subject = f"🔴 {urgent_count} urgent{'s' if urgent_count > 1 else ''} | {subject}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = recipient

    # Version texte (fallback)
    text_lines = [f"VEILLE JURIDIQUE — Semaine du {week}", ""]
    for article in articles:
        level = {"action_urgente": "🔴", "vigilance": "🟡", "information": "🔵"}
        icon = level.get(article.action_level, "•")
        text_lines.append(f"{icon} [{article.relevance_score}] {article.title}")
        if article.summary:
            text_lines.append(f"   {article.summary}")
        text_lines.append(f"   → {article.url}")
        text_lines.append("")

    msg.attach(MIMEText("\n".join(text_lines), "plain", "utf-8"))
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    # Envoi
    try:
        logger.info(f"Envoi du digest à {recipient} via {host}:{port}...")
        with smtplib.SMTP(host, port) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(user, password)
            server.sendmail(user, recipient, msg.as_string())

        logger.info(f"✅ Digest envoyé à {recipient} ({len(articles)} articles)")
        return True

    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"Erreur d'authentification SMTP: {e}")
    except smtplib.SMTPException as e:
        logger.error(f"Erreur SMTP: {e}")
    except Exception as e:
        logger.error(f"Erreur envoi email: {e}")

    return False


def save_digest_local(
    articles: list[Article],
    total_sources: int = 0,
    output_path: str = None,
) -> str:
    """
    Sauvegarde le digest en HTML local (pour prévisualisation/debug).
    
    Returns:
        Chemin du fichier HTML généré
    """
    html = render_digest_html(articles, total_sources)

    if not output_path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = str(Path("data") / f"digest_{timestamp}.html")

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    logger.info(f"Digest sauvegardé : {output_path}")
    return output_path
