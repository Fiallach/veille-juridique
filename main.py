#!/usr/bin/env python3
"""
Orchestrateur principal du pipeline de veille juridique.

Usage :
    python main.py              # Exécution unique (collecte → scoring → email)
    python main.py --dry-run    # Test sans envoi email (sauvegarde locale)
    python main.py --schedule   # Exécution planifiée (hebdomadaire)
"""
import sys
import logging
import argparse
import asyncio
from datetime import datetime

from config.settings import (
    load_user_config, MAX_ARTICLES_PER_DIGEST,
    DIGEST_DAY, DIGEST_HOUR, DIGEST_MINUTE, DATA_DIR,
)
from collectors.rss_collector import collect_from_rss
from collectors.web_scraper import collect_from_website
from collectors.email_parser import collect_from_newsletters
from analysis.scorer import score_articles_batch
from analysis.dedup import deduplicate_articles
from email_sender.sender import send_digest_email, save_digest_local

# === Logging ===
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(DATA_DIR / "veille.log", encoding="utf-8"),
    ]
)
logger = logging.getLogger("veille-juridique")


def run_pipeline(dry_run: bool = False):
    """
    Exécute le pipeline complet :
    1. Chargement config
    2. Collecte (RSS + scraping + newsletters)
    3. Scoring IA
    4. Déduplication
    5. Envoi digest (ou sauvegarde locale si dry_run)
    """
    start = datetime.now()
    logger.info("=" * 60)
    logger.info("🚀 DÉMARRAGE DU PIPELINE DE VEILLE JURIDIQUE")
    logger.info("=" * 60)

    # 1. Charger la configuration
    config = load_user_config()
    expertise = config.get("expertise_domains", "")
    recipient = config.get("recipient_email", "")

    if not expertise:
        logger.error("❌ Aucun domaine d'expertise configuré. Lancez 'streamlit run app.py'.")
        return

    logger.info(f"📌 Domaines : {expertise[:100]}...")
    logger.info(f"📧 Destinataire : {recipient}")

    # 2. COLLECTE
    all_articles = []
    total_sources = 0

    # 2a. Sources publiques (RSS)
    for source in config.get("public_sources", []):
        url = source.get("url", "")
        name = source.get("name", "")
        source_type = source.get("type", "rss")

        if not url:
            continue

        total_sources += 1
        logger.info(f"📡 Collecte RSS : {name or url}")

        try:
            if source_type == "rss":
                articles = collect_from_rss(url, source_name=name)
            else:
                # Scraping pour les sites sans RSS
                articles = asyncio.run(collect_from_website(url, source_name=name))
            all_articles.extend(articles)
        except Exception as e:
            logger.error(f"Erreur collecte {url}: {e}")

    # 2b. Sources privées (avec login)
    for source in config.get("private_sources", []):
        url = source.get("url", "")
        name = source.get("name", "")
        creds = source.get("credentials", {})

        if not url or not creds:
            continue

        total_sources += 1
        logger.info(f"🔐 Collecte privée : {name or url}")

        try:
            articles = asyncio.run(
                collect_from_website(url, source_name=name, credentials=creds)
            )
            all_articles.extend(articles)
        except Exception as e:
            logger.error(f"Erreur collecte privée {url}: {e}")

    # 2c. Newsletters
    if config.get("newsletter_enabled", False):
        logger.info("📬 Collecte newsletters...")
        try:
            newsletter_articles = collect_from_newsletters(
                sender_filter=config.get("newsletter_senders", [])
            )
            all_articles.extend(newsletter_articles)
            total_sources += 1
        except Exception as e:
            logger.error(f"Erreur collecte newsletters: {e}")

    logger.info(f"\n📊 COLLECTE TERMINÉE : {len(all_articles)} articles bruts de {total_sources} sources")

    if not all_articles:
        logger.warning("Aucun article collecté. Vérifiez vos sources.")
        return

    # 3. SCORING IA
    logger.info("\n🤖 SCORING IA EN COURS...")
    scored_articles = score_articles_batch(all_articles, expertise)

    # 4. DÉDUPLICATION
    logger.info("\n🔍 DÉDUPLICATION...")
    unique_articles = deduplicate_articles(scored_articles)

    # Limiter le nombre d'articles
    final_articles = unique_articles[:MAX_ARTICLES_PER_DIGEST]

    # Stats
    urgent = sum(1 for a in final_articles if a.action_level == "action_urgente")
    vigilance = sum(1 for a in final_articles if a.action_level == "vigilance")
    info = sum(1 for a in final_articles if a.action_level == "information")

    logger.info(f"\n📋 RÉSULTATS FINAUX :")
    logger.info(f"   🔴 Action urgente : {urgent}")
    logger.info(f"   🟡 Vigilance      : {vigilance}")
    logger.info(f"   🔵 Information    : {info}")
    logger.info(f"   Total             : {len(final_articles)}")

    # 5. ENVOI / SAUVEGARDE
    if dry_run or not recipient:
        logger.info("\n💾 Mode dry-run : sauvegarde locale du digest...")
        path = save_digest_local(final_articles, total_sources)
        logger.info(f"   → {path}")
    else:
        logger.info(f"\n📧 Envoi du digest à {recipient}...")
        success = send_digest_email(recipient, final_articles, total_sources)
        if success:
            logger.info("✅ Digest envoyé avec succès !")
        else:
            logger.error("❌ Échec de l'envoi. Sauvegarde locale de secours.")
            save_digest_local(final_articles, total_sources)

    elapsed = (datetime.now() - start).total_seconds()
    logger.info(f"\n⏱️ Pipeline terminé en {elapsed:.1f}s")
    logger.info("=" * 60)


def run_scheduled():
    """Lance le pipeline en mode planifié (hebdomadaire)."""
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    scheduler = BlockingScheduler()
    trigger = CronTrigger(
        day_of_week=DIGEST_DAY[:3].lower(),
        hour=DIGEST_HOUR,
        minute=DIGEST_MINUTE,
    )
    scheduler.add_job(run_pipeline, trigger, id="veille_weekly")

    logger.info(
        f"⏰ Planification activée : chaque {DIGEST_DAY} à "
        f"{DIGEST_HOUR:02d}:{DIGEST_MINUTE:02d}"
    )
    logger.info("   Ctrl+C pour arrêter.")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Arrêt du scheduler.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pipeline de veille juridique automatisée")
    parser.add_argument("--dry-run", action="store_true",
                        help="Exécution sans envoi email (sauvegarde locale)")
    parser.add_argument("--schedule", action="store_true",
                        help="Mode planifié (exécution hebdomadaire)")
    args = parser.parse_args()

    # Créer le dossier data si nécessaire
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if args.schedule:
        run_scheduled()
    else:
        run_pipeline(dry_run=args.dry_run)
