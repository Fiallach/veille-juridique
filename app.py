#!/usr/bin/env python3
"""
Interface Streamlit — Veille juridique avec scoring IA via Google Gemini.
"""

import json
import os
import logging
import streamlit as st
from pathlib import Path

from config.settings import (
    load_user_config, save_user_config,
    encrypt_value, ENCRYPTION_KEY, DATA_DIR,
)

MIN_RELEVANCE_SCORE = 30
from collectors.rss_collector import collect_from_rss, Article
from analysis.scorer import get_gemini_client, generate_keywords, prefilter_articles, score_batch
from analysis.dedup import deduplicate_articles

logger = logging.getLogger(__name__)


def get_secret(key: str, default: str = "") -> str:
    try:
        return st.secrets.get(key, default)
    except Exception:
        return os.getenv(key, default)


# === Page config ===
st.set_page_config(page_title="Veille Juridique", page_icon="⚖️", layout="wide", initial_sidebar_state="expanded")

# === CSS Club Med ===
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Noto+Sans:wght@300;400;500;600;700&family=Playfair+Display:wght@500;600;700&display=swap');
    .stApp, .stMarkdown, p, li, span, label, div { font-family: 'Noto Sans', sans-serif !important; }
    h1, h2, h3 { font-family: 'Playfair Display', serif !important; color: #1A1A1A !important; }
    .stApp { max-width: 1080px; margin: 0 auto; }
    .block-container { padding-top: 1.5rem; }
    .stTabs [data-baseweb="tab-list"] { background: #F5F5F3; border-radius: 10px; padding: 4px; gap: 4px; }
    .stTabs [data-baseweb="tab"] { font-weight: 500 !important; font-size: 14px !important; color: #4A4A4A !important; background: transparent !important; border-radius: 8px !important; padding: 10px 18px !important; border: none !important; white-space: nowrap !important; }
    .stTabs [data-baseweb="tab"]:hover { background: rgba(0,87,160,0.07) !important; color: #0057A0 !important; }
    .stTabs [aria-selected="true"] { background: #FFF !important; color: #0057A0 !important; font-weight: 600 !important; box-shadow: 0 1px 4px rgba(0,0,0,0.1) !important; }
    .stTabs [data-baseweb="tab-highlight"] { background-color: #0057A0 !important; }
    .stTabs [data-baseweb="tab-border"] { display: none !important; }
    section[data-testid="stSidebar"] { background: #0057A0 !important; }
    section[data-testid="stSidebar"] > div:first-child { padding: 1.5rem 1.2rem !important; }
    section[data-testid="stSidebar"] .stMarkdown, section[data-testid="stSidebar"] p,
    section[data-testid="stSidebar"] li, section[data-testid="stSidebar"] span,
    section[data-testid="stSidebar"] label, section[data-testid="stSidebar"] h1,
    section[data-testid="stSidebar"] h2, section[data-testid="stSidebar"] h3 { color: #FFF !important; }
    section[data-testid="stSidebar"] .stCaption p { color: rgba(255,255,255,0.7) !important; }
    section[data-testid="stSidebar"] hr { border-color: rgba(255,255,255,0.2) !important; }
    section[data-testid="stSidebar"] .stButton button { background: rgba(255,255,255,0.15) !important; color: #FFF !important; border: 1px solid rgba(255,255,255,0.3) !important; border-radius: 8px !important; }
    button[data-testid="stBaseButton-primary"] { background: #0057A0 !important; color: #FFF !important; border: none !important; border-radius: 8px !important; font-weight: 600 !important; }
    button[data-testid="stBaseButton-primary"]:hover { background: #003F73 !important; }
    .stTextInput input, .stTextArea textarea { border: 1.5px solid #D4D4D4 !important; border-radius: 8px !important; }
    .stTextInput input:focus, .stTextArea textarea:focus { border-color: #0057A0 !important; box-shadow: 0 0 0 2px rgba(0,87,160,0.12) !important; }
    div[data-testid="stMetric"] { background: #F5F5F3; border-radius: 10px; padding: 14px 18px; }
    div[data-testid="stMetric"] div[data-testid="stMetricValue"] { color: #0057A0 !important; font-weight: 700 !important; }
    .launch-zone { background: linear-gradient(135deg, #0057A0 0%, #003F73 100%); border-radius: 14px; padding: 28px 32px; margin-top: 40px; color: white; }
    .launch-zone h3 { color: #FFF !important; margin-bottom: 8px; }
    .launch-zone p { color: rgba(255,255,255,0.85) !important; font-size: 14px; }
    #MainMenu { visibility: hidden; } footer { visibility: hidden; } header { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

# === Config ===
if "config" not in st.session_state:
    st.session_state.config = load_user_config()
config = st.session_state.config

st.title("⚖️ Veille Juridique Automatisée")
st.caption("Configurez vos sources, domaines d'expertise et préférences de digest.")

tab1, tab2, tab3, tab4, tab5 = st.tabs(["🎯 Expertise", "📡 Sources", "🔐 Sources privées", "📬 Newsletters", "⚙️ Paramètres"])


# ── TAB 1 : EXPERTISE ──
with tab1:
    st.header("Domaines d'expertise")
    with st.container(border=True):
        st.markdown("**💡 Comment bien renseigner vos domaines**")
        st.markdown("""
Vos domaines sont traités comme **alternatifs** : un article sera retenu s'il touche **au moins un** de vos domaines.
- **Listez chaque domaine séparément**
- **Précisez votre secteur**
- **Ajoutez vos sujets prioritaires**
""")
        if st.button("✨ Template d'exemple", key="template_btn"):
            st.session_state["show_template"] = True
        if st.session_state.get("show_template"):
            st.code("""Domaine 1 : Droit du tourisme (Code du tourisme, vente de séjours)
Domaine 2 : Droit des marques (propriété intellectuelle, contrefaçon, co-branding)
Domaine 3 : Droit de la consommation (publicité loyale, promotions, pratiques commerciales trompeuses)
Secteur : Tourisme / hôtellerie""", language=None)

    st.info("⚠️ Chaque domaine est évalué **indépendamment**.")
    expertise = st.text_area("Description de vos domaines", value=config.get("expertise_domains", ""), height=200,
        placeholder="Domaine 1 : Droit du tourisme\nDomaine 2 : Droit des marques\n...")
    config["expertise_domains"] = expertise
    st.divider()
    st.subheader("Email du destinataire")
    config["recipient_email"] = st.text_input("Email", value=config.get("recipient_email", ""), placeholder="prenom.nom@entreprise.com")


# ── TAB 2 : SOURCES ──
with tab2:
    st.header("Sources de veille")
    st.info("Entrez une URL. L'app détecte le RSS automatiquement, sinon scrape la page.")
    public_sources = config.get("public_sources", [])
    sources_to_remove = []
    for i, source in enumerate(public_sources):
        col1, col2, col3 = st.columns([4, 3, 0.5])
        with col1:
            source["url"] = st.text_input("URL", value=source.get("url", ""), key=f"pub_url_{i}", label_visibility="collapsed", placeholder="https://www.cnil.fr")
        with col2:
            source["name"] = st.text_input("Nom", value=source.get("name", ""), key=f"pub_name_{i}", label_visibility="collapsed", placeholder="Nom")
        with col3:
            if st.button("🗑", key=f"pub_del_{i}"):
                sources_to_remove.append(i)
    for idx in sorted(sources_to_remove, reverse=True):
        public_sources.pop(idx); st.rerun()

    st.divider()
    with st.expander("➕ Ajouter une source"):
        new_url = st.text_input("URL", key="new_pub_url", placeholder="https://www.cnil.fr")
        new_name = st.text_input("Nom (optionnel)", key="new_pub_name")
        st.caption("Détection RSS automatique. Sinon, scraping.")
        if st.button("Ajouter", key="btn_add_pub"):
            if new_url:
                public_sources.append({"url": new_url.strip(), "name": new_name.strip() or new_url.split("//")[-1].split("/")[0]})
                st.success(f"✅ {new_name or new_url}"); st.rerun()

    st.divider()
    st.subheader("💡 Suggérées")
    suggested = [
        {"url": "https://www.village-justice.com", "name": "Village de la Justice"},
        {"url": "https://www.cnil.fr", "name": "CNIL"},
        {"url": "https://www.dalloz-actualite.fr", "name": "Dalloz Actualité"},
        {"url": "https://www.actu-juridique.fr", "name": "Actu-Juridique.fr"},
        {"url": "https://www.conseil-constitutionnel.fr", "name": "Conseil constitutionnel"},
        {"url": "https://curia.europa.eu", "name": "CJUE"},
        {"url": "https://eur-lex.europa.eu", "name": "EUR-Lex"},
        {"url": "https://www.economie.gouv.fr/dgccrf", "name": "DGCCRF"},
    ]
    cols = st.columns(4)
    for i, s in enumerate(suggested):
        with cols[i % 4]:
            if any(s["url"] in src.get("url", "") for src in public_sources):
                st.button(f"✅ {s['name']}", key=f"sug_{i}", disabled=True)
            else:
                if st.button(f"➕ {s['name']}", key=f"sug_{i}"):
                    public_sources.append(s.copy()); st.rerun()
    config["public_sources"] = public_sources


# ── TAB 3 : SOURCES PRIVÉES ──
with tab3:
    st.header("Sources privées")
    st.warning("⚠️ Identifiants chiffrés localement (AES-256).")
    if not ENCRYPTION_KEY:
        st.error("🔴 ENCRYPTION_KEY non configurée.")
    private_sources = config.get("private_sources", [])
    for i, source in enumerate(private_sources):
        st.markdown(f"**{source.get('name', f'Source {i+1}')}**")
        col1, col2 = st.columns(2)
        with col1:
            source["url"] = st.text_input("URL", value=source.get("url", ""), key=f"priv_url_{i}")
            source["name"] = st.text_input("Nom", value=source.get("name", ""), key=f"priv_name_{i}")
        with col2:
            creds = source.get("credentials", {})
            creds["username"] = st.text_input("Identifiant", value=creds.get("username", ""), key=f"priv_user_{i}")
            new_pass = st.text_input("Mot de passe", type="password", key=f"priv_pass_{i}")
            if new_pass and ENCRYPTION_KEY: creds["password_encrypted"] = encrypt_value(new_pass)
            source["credentials"] = creds
        if st.button("🗑 Supprimer", key=f"priv_del_{i}"):
            private_sources.pop(i); st.rerun()
        st.divider()
    config["private_sources"] = private_sources


# ── TAB 4 : NEWSLETTERS ──
with tab4:
    st.header("Newsletters")
    config["newsletter_enabled"] = st.toggle("Activer", value=config.get("newsletter_enabled", False))
    if config["newsletter_enabled"]:
        senders = config.get("newsletter_senders", [])
        senders_text = st.text_area("Adresses (une par ligne)", value="\n".join(senders), height=150)
        config["newsletter_senders"] = [s.strip() for s in senders_text.strip().split("\n") if s.strip()]


# ── TAB 5 : PARAMÈTRES ──
with tab5:
    st.header("Paramètres")
    col1, col2, col3 = st.columns(3)
    col1.metric("Sources", len(config.get("public_sources", [])))
    col2.metric("Privées", len(config.get("private_sources", [])))
    col3.metric("Newsletters", "✅" if config.get("newsletter_enabled") else "❌")
    st.divider()
    config["frequency"] = st.selectbox("Fréquence", ["weekly", "daily", "biweekly"],
        index=["weekly", "daily", "biweekly"].index(config.get("frequency", "weekly")),
        format_func=lambda x: {"weekly": "Hebdomadaire", "daily": "Quotidien", "biweekly": "Bimensuel"}[x])
    st.divider()
    if st.button("💾 Sauvegarder", type="primary"):
        save_user_config(config); st.success("✅ Sauvegardé !")


# ══════════════════════════════════════════════
# ZONE DE LANCEMENT
# ══════════════════════════════════════════════
st.markdown("---")
st.markdown("""
<div class="launch-zone">
    <h3>🚀 Lancer la veille</h3>
    <p>Pipeline optimisé : mots-clés IA → pré-filtrage local → scoring batch.<br>
    ~4 appels API au lieu de 1 par article. Propulsé par <strong>Google Gemini Flash</strong>.</p>
</div>
""", unsafe_allow_html=True)

has_sources = len(config.get("public_sources", [])) > 0
has_expertise = len(config.get("expertise_domains", "")) > 20
api_key = get_secret("GEMINI_API_KEY")

if not has_sources: st.warning("⚠️ Ajoutez des sources dans l'onglet **Sources**.")
if not has_expertise: st.warning("⚠️ Décrivez vos domaines dans **Expertise**.")
if not api_key: st.error("🔑 Clé API manquante. Configurez `GEMINI_API_KEY` dans les secrets Streamlit Cloud.")

can_launch = has_sources and has_expertise and bool(api_key)
frequency = config.get("frequency", "weekly")
days_back = {"daily": 1, "weekly": 7, "biweekly": 14}.get(frequency, 7)
freq_label = {"daily": "24h", "weekly": "7 jours", "biweekly": "14 jours"}.get(frequency, "7 jours")
st.caption(f"📅 Période : **{freq_label}**")

if st.button("▶️  Lancer la collecte et l'analyse IA", type="primary", use_container_width=True, disabled=not can_launch):

    save_user_config(config)
    all_articles = []

    # ═══ ÉTAPE 1 : Collecte ═══
    with st.status(f"🔍 Collecte ({freq_label})...", expanded=True) as status:
        for source in config.get("public_sources", []):
            st.write(f"📡 {source.get('name', source['url'])}...")
            try:
                articles = collect_from_rss(source["url"], source_name=source.get("name", ""), days_back=days_back)
                all_articles.extend(articles)
                st.write(f"   ✅ {len(articles)} articles")
            except Exception as e:
                st.write(f"   ❌ {e}")
        status.update(label=f"📊 {len(all_articles)} articles collectés", state="complete")

    if not all_articles:
        st.warning("Aucun article collecté."); st.stop()

    # ═══ ÉTAPE 2 : Connexion Gemini + Mots-clés ═══
    with st.status("🔑 Connexion Gemini + mots-clés...", expanded=True) as status:
        try:
            client = get_gemini_client(api_key)
            test = client.models.generate_content(model="gemini-2.5-flash", contents="Réponds OK.")
            st.write(f"✅ API Gemini connectée")
        except Exception as e:
            st.error(f"🔴 Erreur API Gemini : {type(e).__name__}: {e}")
            status.update(label="❌ Erreur API", state="error"); st.stop()

        expertise = config.get("expertise_domains", "")
        st.write("🧠 Génération des mots-clés... (1 appel)")
        keywords = generate_keywords(expertise, client)
        st.write(f"✅ {len(keywords)} mots-clés générés")
        with st.expander(f"Voir les mots-clés ({len(keywords)})"):
            st.write(", ".join(keywords[:60]))
        status.update(label=f"🧠 {len(keywords)} mots-clés", state="complete")

    # ═══ ÉTAPE 3 : Pré-filtrage ═══
    with st.status("🔎 Pré-filtrage...", expanded=True) as status:
        candidates, rejected = prefilter_articles(all_articles, keywords)
        st.write(f"✅ **{len(candidates)}** candidats / {len(rejected)} filtrés")
        status.update(label=f"🔎 {len(candidates)} candidats", state="complete")

    if not candidates:
        st.warning("Aucun article ne matche vos mots-clés."); st.stop()

    # ═══ ÉTAPE 4 : Scoring batch ═══
    batch_size = 10
    n_batches = (len(candidates) + batch_size - 1) // batch_size

    with st.status(f"🤖 Scoring de {len(candidates)} articles ({n_batches} batch)...", expanded=True) as status:
        scored_articles = score_batch(candidates, expertise, client, batch_size=batch_size)
        for a in scored_articles:
            if a.relevance_score > 0:
                st.write(f"  ✅ {a.relevance_score}/100 — {a.title[:60]}")
        status.update(label=f"🤖 Scoring terminé ({n_batches} appels)", state="complete")

    # ═══ RÉSULTATS ═══
    relevant = [a for a in scored_articles if a.relevance_score >= MIN_RELEVANCE_SCORE]
    relevant = deduplicate_articles(relevant)
    relevant.sort(key=lambda a: a.relevance_score, reverse=True)

    all_scores = [a.relevance_score for a in scored_articles]
    with st.expander(f"🔍 Diagnostic", expanded=(len(relevant) == 0)):
        st.write(f"Seuil: {MIN_RELEVANCE_SCORE} | Max: {max(all_scores) if all_scores else 0} | Moy: {sum(all_scores)//max(len(all_scores),1)}")
        st.write(f"Appels API: ~{1 + n_batches} (1 mots-clés + {n_batches} batch)")
        for a in sorted(scored_articles, key=lambda a: a.relevance_score, reverse=True)[:10]:
            st.write(f"{'✅' if a.relevance_score >= MIN_RELEVANCE_SCORE else '❌'} **{a.relevance_score}** — {a.title[:80]}")

    st.markdown("---")
    st.header(f"📋 {len(relevant)} articles pertinents")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("🔴 Urgent", len([a for a in relevant if a.action_level == "action_urgente"]))
    col2.metric("🟡 Vigilance", len([a for a in relevant if a.action_level == "vigilance"]))
    col3.metric("🔵 Info", len([a for a in relevant if a.action_level == "information"]))
    col4.metric("Total", f"{len(relevant)}/{len(all_articles)}")

    for article in relevant:
        icon = {"action_urgente": "🔴", "vigilance": "🟡"}.get(article.action_level, "🔵")
        with st.expander(f"{icon} **{article.title}** — {article.source_name} ({article.relevance_score}/100)"):
            if article.summary: st.write(article.summary)
            if article.tags: st.write("**Tags :** " + ", ".join(article.tags))
            if article.url: st.markdown(f"[🔗 Lire l'article]({article.url})")


# ══════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════
with st.sidebar:
    st.markdown("### ⚖️ Outils")
    if st.button("📋 Exporter config"):
        st.download_button("Télécharger", data=json.dumps(config, indent=2, ensure_ascii=False),
                           file_name="veille_config.json", mime="application/json")
    st.divider()
    st.markdown("### 📖 Guide")
    st.markdown("1. **Expertise** : décrivez vos domaines\n2. **Sources** : ajoutez des URLs\n3. **Lancez** en bas de page !")
    st.divider()
    st.caption("Veille Juridique IA v1.0 — Gemini Flash")
