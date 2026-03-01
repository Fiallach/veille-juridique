"""
Parseur de newsletters par email.
Se connecte à une boîte IMAP dédiée, lit les emails récents,
et extrait les liens et contenus des newsletters juridiques.
"""
import imaplib
import email
import logging
import re
from datetime import datetime, timedelta
from email.header import decode_header
from typing import Optional

from bs4 import BeautifulSoup

from collectors.rss_collector import Article
from config.settings import IMAP_HOST, IMAP_USER, IMAP_PASSWORD

logger = logging.getLogger(__name__)


# Expéditeurs connus de newsletters juridiques
KNOWN_NEWSLETTER_SENDERS = {
    "dalloz": ["newsletter@dalloz.fr", "info@dalloz.fr"],
    "lexisnexis": ["newsletter@lexisnexis.fr", "info@lexisnexis.fr"],
    "lamy": ["newsletter@lamy.fr", "info@lamyline.fr"],
    "village-justice": ["newsletter@village-justice.com"],
    "legifrance": ["no-reply@legifrance.gouv.fr"],
    "cnil": ["newsletter@cnil.fr"],
    "efl": ["newsletter@efl.fr"],
    "editions-legislatives": ["newsletter@editions-legislatives.fr"],
    "actualite-juridique": ["newsletter@actualite-juridique.fr"],
}


def decode_email_subject(subject: str) -> str:
    """Décode le sujet de l'email (gestion encodages)."""
    if not subject:
        return "Sans objet"
    decoded_parts = decode_header(subject)
    parts = []
    for part, charset in decoded_parts:
        if isinstance(part, bytes):
            parts.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            parts.append(part)
    return " ".join(parts)


def extract_links_from_html(html_content: str, base_domain: str = "") -> list[dict]:
    """
    Extrait les liens pertinents du HTML d'une newsletter.
    Filtre les liens de désinscription, tracking, etc.
    
    Returns:
        Liste de {"title": ..., "url": ...}
    """
    soup = BeautifulSoup(html_content, "lxml")
    links = []
    seen_urls = set()

    # Patterns à exclure
    exclude_patterns = [
        r"unsubscribe", r"désabonner", r"desinscription",
        r"mailto:", r"tel:", r"#",
        r"facebook\.com", r"twitter\.com", r"linkedin\.com",
        r"instagram\.com", r"youtube\.com",
        r"utm_", r"click\.email", r"track\.",
        r"manage.*preferences", r"view.*browser",
    ]
    exclude_regex = re.compile("|".join(exclude_patterns), re.IGNORECASE)

    for a in soup.find_all("a", href=True):
        url = a.get("href", "").strip()

        # Filtrer
        if not url or url.startswith("#") or url.startswith("mailto:"):
            continue
        if exclude_regex.search(url):
            continue
        if url in seen_urls:
            continue
        if len(url) < 20:
            continue

        # Titre du lien
        title = a.get_text(strip=True)
        if not title or len(title) < 5:
            # Chercher un titre dans le contexte parent
            parent = a.parent
            if parent:
                title = parent.get_text(strip=True)[:150]

        if title and len(title) >= 5:
            seen_urls.add(url)
            links.append({"title": title[:200], "url": url})

    return links


def extract_text_content(msg: email.message.Message) -> tuple[str, str]:
    """
    Extrait le contenu texte et HTML d'un email.
    
    Returns:
        (text_content, html_content)
    """
    text_content = ""
    html_content = ""

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))

            if "attachment" in content_disposition:
                continue

            try:
                body = part.get_payload(decode=True)
                if body is None:
                    continue
                charset = part.get_content_charset() or "utf-8"
                decoded = body.decode(charset, errors="replace")

                if content_type == "text/plain":
                    text_content = decoded
                elif content_type == "text/html":
                    html_content = decoded
            except Exception:
                continue
    else:
        content_type = msg.get_content_type()
        try:
            body = msg.get_payload(decode=True)
            if body:
                charset = msg.get_content_charset() or "utf-8"
                decoded = body.decode(charset, errors="replace")
                if content_type == "text/plain":
                    text_content = decoded
                elif content_type == "text/html":
                    html_content = decoded
        except Exception:
            pass

    return text_content, html_content


def collect_from_newsletters(
    days_back: int = 7,
    imap_host: Optional[str] = None,
    imap_user: Optional[str] = None,
    imap_password: Optional[str] = None,
    sender_filter: Optional[list[str]] = None,
) -> list[Article]:
    """
    Collecte les articles depuis les newsletters reçues par email.
    
    Args:
        days_back: Nombre de jours en arrière
        imap_host: Serveur IMAP (défaut: settings)
        imap_user: Utilisateur IMAP (défaut: settings)
        imap_password: Mot de passe IMAP (défaut: settings)
        sender_filter: Liste d'emails expéditeurs à inclure (optionnel)
    
    Returns:
        Liste d'objets Article
    """
    host = imap_host or IMAP_HOST
    user = imap_user or IMAP_USER
    password = imap_password or IMAP_PASSWORD

    if not all([host, user, password]):
        logger.warning("Configuration IMAP incomplète, skip newsletters.")
        return []

    articles = []
    cutoff = datetime.now() - timedelta(days=days_back)
    date_str = cutoff.strftime("%d-%b-%Y")

    try:
        # Connexion IMAP
        logger.info(f"Connexion IMAP à {host}...")
        mail = imaplib.IMAP4_SSL(host)
        mail.login(user, password)
        mail.select("INBOX")

        # Rechercher les emails récents
        search_criteria = f'(SINCE {date_str})'
        _, message_ids = mail.search(None, search_criteria)

        if not message_ids[0]:
            logger.info("Aucun email récent trouvé.")
            return []

        ids = message_ids[0].split()
        logger.info(f"{len(ids)} emails trouvés depuis {date_str}")

        for msg_id in ids:
            try:
                _, msg_data = mail.fetch(msg_id, "(RFC822)")
                msg = email.message_from_bytes(msg_data[0][1])

                # Vérifier l'expéditeur
                from_header = msg.get("From", "")
                from_email = ""
                match = re.search(r"<(.+?)>", from_header)
                if match:
                    from_email = match.group(1).lower()
                else:
                    from_email = from_header.strip().lower()

                # Filtrer par expéditeur si un filtre est défini
                if sender_filter:
                    if not any(s.lower() in from_email for s in sender_filter):
                        continue

                # Identifier la source
                source_name = "Newsletter"
                for name, senders in KNOWN_NEWSLETTER_SENDERS.items():
                    if any(s in from_email for s in senders):
                        source_name = f"Newsletter {name.title()}"
                        break

                # Extraire le contenu
                text_content, html_content = extract_text_content(msg)
                subject = decode_email_subject(msg.get("Subject", ""))

                # Extraire les liens de la newsletter
                if html_content:
                    links = extract_links_from_html(html_content)

                    for link_info in links:
                        article = Article(
                            title=link_info["title"],
                            url=link_info["url"],
                            source_name=source_name,
                            source_type="newsletter",
                            published_date=msg.get("Date", ""),
                            content_extract=f"[Newsletter: {subject}] {link_info['title']}",
                        )
                        articles.append(article)

                elif text_content:
                    # Extraire les URLs du texte brut
                    urls = re.findall(r'https?://\S+', text_content)
                    for url in urls[:10]:
                        article = Article(
                            title=subject,
                            url=url.rstrip(".,;)>"),
                            source_name=source_name,
                            source_type="newsletter",
                            published_date=msg.get("Date", ""),
                            content_extract=text_content[:500],
                        )
                        articles.append(article)

            except Exception as e:
                logger.debug(f"Erreur traitement email {msg_id}: {e}")
                continue

        mail.logout()

    except Exception as e:
        logger.error(f"Erreur connexion IMAP: {e}")

    logger.info(f"Newsletters: {len(articles)} articles extraits")
    return articles
