#!/usr/bin/env python3
"""
Interface de configuration Streamlit pour l'outil de veille juridique.
Lance avec : streamlit run app.py
"""

import json
import streamlit as st
from pathlib import Path

from config.settings import (
    load_user_config, save_user_config,
    encrypt_value, ENCRYPTION_KEY, DATA_DIR,
)

# === Page config ===
st.set_page_config(
    page_title="Veille Juridique — Configuration",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# === Custom CSS — Design inspiré Club Med ===
st.markdown("""
<style>
    /* ── Polices ── */
    @import url('https://fonts.googleapis.com/css2?family=Noto+Sans:wght@300;400;500;600;700&family=Playfair+Display:wght@500;600;700&display=swap');

    .stApp, .stMarkdown, p, li, span, label, div {
        font-family: 'Noto Sans', sans-serif !important;
    }
    h1, h2, h3 {
        font-family: 'Playfair Display', serif !important;
        color: #1A1A1A !important;
    }

    /* ── Layout ── */
    .stApp { max-width: 1080px; margin: 0 auto; }
    .block-container { padding-top: 1.5rem; }

    /* ── Onglets — FIX LISIBILITÉ ── */
    .stTabs [data-baseweb="tab-list"] {
        background: #F5F5F3;
        border-radius: 10px;
        padding: 4px;
        gap: 4px;
    }
    .stTabs [data-baseweb="tab"] {
        font-family: 'Noto Sans', sans-serif !important;
        font-weight: 500 !important;
        font-size: 14px !important;
        color: #4A4A4A !important;
        background: transparent !important;
        border-radius: 8px !important;
        padding: 10px 18px !important;
        border: none !important;
        white-space: nowrap !important;
    }
    .stTabs [data-baseweb="tab"]:hover {
        background: rgba(0, 87, 160, 0.07) !important;
        color: #0057A0 !important;
    }
    .stTabs [aria-selected="true"] {
        background: #FFFFFF !important;
        color: #0057A0 !important;
        font-weight: 600 !important;
        box-shadow: 0 1px 4px rgba(0,0,0,0.1) !important;
    }
    .stTabs [data-baseweb="tab-highlight"] {
        background-color: #0057A0 !important;
    }
    .stTabs [data-baseweb="tab-border"] {
        display: none !important;
    }

    /* ── Sidebar bleu marine ── */
    section[data-testid="stSidebar"] {
        background: #0057A0 !important;
    }
    section[data-testid="stSidebar"] > div:first-child {
        padding: 1.5rem 1.2rem !important;
    }
    section[data-testid="stSidebar"] .stMarkdown,
    section[data-testid="stSidebar"] p,
    section[data-testid="stSidebar"] li,
    section[data-testid="stSidebar"] span,
    section[data-testid="stSidebar"] label,
    section[data-testid="stSidebar"] h1,
    section[data-testid="stSidebar"] h2,
    section[data-testid="stSidebar"] h3 {
        color: #FFFFFF !important;
    }
    section[data-testid="stSidebar"] .stCaption p {
        color: rgba(255,255,255,0.7) !important;
    }
    section[data-testid="stSidebar"] hr {
        border-color: rgba(255,255,255,0.2) !important;
    }
    section[data-testid="stSidebar"] .stButton button {
        background: rgba(255,255,255,0.15) !important;
        color: #FFFFFF !important;
        border: 1px solid rgba(255,255,255,0.3) !important;
        border-radius: 8px !important;
        font-family: 'Noto Sans', sans-serif !important;
    }
    section[data-testid="stSidebar"] .stButton button:hover {
        background: rgba(255,255,255,0.25) !important;
    }

    /* ── Boutons principaux ── */
    .stButton button[kind="primary"],
    button[data-testid="stBaseButton-primary"] {
        background: #0057A0 !important;
        color: #FFFFFF !important;
        border: none !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
        font-family: 'Noto Sans', sans-serif !important;
        transition: all 0.2s ease !important;
    }
    .stButton button[kind="primary"]:hover,
    button[data-testid="stBaseButton-primary"]:hover {
        background: #003F73 !important;
        box-shadow: 0 4px 12px rgba(0,87,160,0.25) !important;
    }

    /* ── Boutons secondaires ── */
    .stButton button[kind="secondary"],
    button[data-testid="stBaseButton-secondary"] {
        border: 1.5px solid #0057A0 !important;
        color: #0057A0 !important;
        background: transparent !important;
        border-radius: 8px !important;
    }

    /* ── Inputs ── */
    .stTextInput input, .stTextArea textarea {
        border: 1.5px solid #D4D4D4 !important;
        border-radius: 8px !important;
        font-family: 'Noto Sans', sans-serif !important;
    }
    .stTextInput input:focus, .stTextArea textarea:focus {
        border-color: #0057A0 !important;
        box-shadow: 0 0 0 2px rgba(0,87,160,0.12) !important;
    }

    /* ── Métriques ── */
    div[data-testid="stMetric"] {
        background: #F5F5F3;
        border-radius: 10px;
        padding: 14px 18px;
    }
    div[data-testid="stMetric"] label {
        color: #767676 !important;
    }
    div[data-testid="stMetric"] div[data-testid="stMetricValue"] {
        color: #0057A0 !important;
        font-weight: 700 !important;
    }

    /* ── Cards sources ── */
    .source-card {
        border: 1px solid #E8E8E8;
        border-radius: 10px;
        padding: 16px;
        margin-bottom: 12px;
        background: #FAFAFA;
    }

    /* ── Statuts ── */
    .status-ok { color: #16a34a; font-weight: 600; }
    .status-warn { color: #d97706; font-weight: 600; }
    .status-error { color: #dc2626; font-weight: 600; }

    /* ── Expanders ── */
    div[data-testid="stExpander"] {
        border: 1px solid #E8E8E8 !important;
        border-radius: 10px !important;
    }
    div[data-testid="stExpander"]:hover {
        border-color: #0057A0 !important;
    }

    /* ── Dividers ── */
    hr { border-color: #E8E8E8 !important; }

    /* ── Masquer éléments Streamlit par défaut ── */
    #MainMenu { visibility: hidden; }
    footer { visibility: hidden; }
    header { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

# === Load config ===
if "config" not in st.session_state:
    st.session_state.config = load_user_config()
config = st.session_state.config

# === Header ===
st.title("⚖️ Veille Juridique Automatisée")
st.caption("Configurez vos sources, domaines d'expertise et préférences de digest.")

# === Tabs ===
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "🎯 Expertise",
    "📡 Sources publiques",
    "🔐 Sources privées",
    "📬 Newsletters",
    "📧 Envoi & Test"
])

# ============================================
# TAB 1 : DOMAINES D'EXPERTISE
# ============================================
with tab1:
    st.header("Domaines d'expertise")
    st.info(
        "Décrivez vos domaines d'expertise en langage naturel. "
        "L'IA utilisera cette description pour évaluer la pertinence des articles."
    )

    expertise = st.text_area(
        "Description de vos domaines",
        value=config.get("expertise_domains", ""),
        height=200,
        placeholder=(
            "Ex : Juriste d'entreprise spécialisé en droit du tourisme "
            "(Code du tourisme), droit de la consommation (publicité loyale, "
            "annonces de réduction de prix, pratiques commerciales trompeuses), "
            "RGPD, droit des marques et propriété intellectuelle. "
            "Secteur : tourisme / hôtellerie de vacances. "
            "Intérêt particulier pour : réglementation des promotions, "
            "green claims, influenceurs, jeux-concours, droit à l'image."
        ),
    )
    config["expertise_domains"] = expertise

    st.divider()

    st.subheader("Email du destinataire")
    recipient = st.text_input(
        "Adresse email pour recevoir le digest",
        value=config.get("recipient_email", ""),
        placeholder="prenom.nom@entreprise.com",
    )
    config["recipient_email"] = recipient


# ============================================
# TAB 2 : SOURCES PUBLIQUES
# ============================================
with tab2:
    st.header("Sources publiques (RSS / Scraping)")
    st.info("Sites accessibles sans authentification. Les flux RSS seront détectés automatiquement.")

    public_sources = config.get("public_sources", [])

    # Afficher les sources existantes
    sources_to_remove = []
    for i, source in enumerate(public_sources):
        col1, col2, col3, col4 = st.columns([3, 2, 1, 0.5])

        with col1:
            source["url"] = st.text_input(
                "URL", value=source.get("url", ""),
                key=f"pub_url_{i}", label_visibility="collapsed",
                placeholder="https://www.dalloz-actualite.fr",
            )
        with col2:
            source["name"] = st.text_input(
                "Nom", value=source.get("name", ""),
                key=f"pub_name_{i}", label_visibility="collapsed",
                placeholder="Nom de la source",
            )
        with col3:
            source["type"] = st.selectbox(
                "Type", ["rss", "scrape"],
                key=f"pub_type_{i}",
                index=0 if source.get("type", "rss") == "rss" else 1,
                label_visibility="collapsed",
            )
        with col4:
            if st.button("🗑", key=f"pub_del_{i}"):
                sources_to_remove.append(i)

    # Supprimer les sources marquées
    for idx in sorted(sources_to_remove, reverse=True):
        public_sources.pop(idx)
        st.rerun()

    # Ajouter une nouvelle source
    st.divider()
    with st.expander("➕ Ajouter une source publique"):
        new_url = st.text_input(
            "URL du site", key="new_pub_url",
            placeholder="https://www.legifrance.gouv.fr",
        )
        new_name = st.text_input(
            "Nom affiché", key="new_pub_name",
            placeholder="Légifrance",
        )
        new_type = st.selectbox("Type de collecte", ["rss", "scrape"], key="new_pub_type")

        if st.button("Ajouter", key="btn_add_pub"):
            if new_url:
                public_sources.append({
                    "url": new_url.strip(),
                    "name": new_name.strip() or new_url.split("//")[-1].split("/")[0],
                    "type": new_type,
                })
                st.success(f"✅ Source ajoutée : {new_name or new_url}")
                st.rerun()

    # Sources suggérées
    st.divider()
    st.subheader("💡 Sources suggérées")

    suggested = [
        {"url": "https://www.legifrance.gouv.fr", "name": "Légifrance", "type": "rss"},
        {"url": "https://www.dalloz-actualite.fr", "name": "Dalloz Actualité", "type": "rss"},
        {"url": "https://www.village-justice.com", "name": "Village de la Justice", "type": "rss"},
        {"url": "https://www.cnil.fr", "name": "CNIL", "type": "rss"},
        {"url": "https://eur-lex.europa.eu", "name": "EUR-Lex", "type": "rss"},
        {"url": "https://www.economie.gouv.fr/dgccrf", "name": "DGCCRF", "type": "scrape"},
        {"url": "https://www.conseil-constitutionnel.fr", "name": "Conseil constitutionnel", "type": "rss"},
        {"url": "https://curia.europa.eu", "name": "CJUE", "type": "rss"},
    ]

    cols = st.columns(4)
    for i, s in enumerate(suggested):
        with cols[i % 4]:
            already_added = any(
                s["url"] in src.get("url", "") for src in public_sources
            )
            if already_added:
                st.button(f"✅ {s['name']}", key=f"sug_{i}", disabled=True)
            else:
                if st.button(f"➕ {s['name']}", key=f"sug_{i}"):
                    public_sources.append(s.copy())
                    st.rerun()

    config["public_sources"] = public_sources


# ============================================
# TAB 3 : SOURCES PRIVÉES
# ============================================
with tab3:
    st.header("Sources privées (avec authentification)")
    st.warning(
        "⚠️ Les identifiants sont chiffrés localement (AES-256 via Fernet). "
        "Assurez-vous d'avoir configuré `ENCRYPTION_KEY` dans votre fichier `.env`."
    )

    if not ENCRYPTION_KEY:
        st.error(
            "🔴 `ENCRYPTION_KEY` non configurée. Générez-la avec :\n\n"
            "```python\nfrom cryptography.fernet import Fernet\n"
            "print(Fernet.generate_key().decode())\n```"
        )

    private_sources = config.get("private_sources", [])

    for i, source in enumerate(private_sources):
        with st.container():
            st.markdown(f"**{source.get('name', f'Source {i+1}')}**")
            col1, col2 = st.columns(2)
            with col1:
                source["url"] = st.text_input(
                    "URL", value=source.get("url", ""), key=f"priv_url_{i}",
                )
                source["name"] = st.text_input(
                    "Nom", value=source.get("name", ""), key=f"priv_name_{i}",
                )
            with col2:
                creds = source.get("credentials", {})
                creds["username"] = st.text_input(
                    "Identifiant", value=creds.get("username", ""),
                    key=f"priv_user_{i}",
                )
                new_pass = st.text_input(
                    "Mot de passe", type="password", key=f"priv_pass_{i}",
                    placeholder="Laisser vide pour ne pas modifier",
                )
                if new_pass and ENCRYPTION_KEY:
                    creds["password_encrypted"] = encrypt_value(new_pass)
                source["credentials"] = creds

            if st.button("🗑 Supprimer", key=f"priv_del_{i}"):
                private_sources.pop(i)
                st.rerun()
        st.divider()

    # Ajouter
    with st.expander("➕ Ajouter une source privée"):
        np_url = st.text_input("URL", key="new_priv_url", placeholder="https://www.lexis360.fr")
        np_name = st.text_input("Nom", key="new_priv_name", placeholder="Lexis 360")
        np_user = st.text_input("Identifiant", key="new_priv_user")
        np_pass = st.text_input("Mot de passe", type="password", key="new_priv_pass")

        if st.button("Ajouter", key="btn_add_priv"):
            if np_url and np_user and np_pass:
                if ENCRYPTION_KEY:
                    private_sources.append({
                        "url": np_url.strip(),
                        "name": np_name.strip(),
                        "credentials": {
                            "username": np_user.strip(),
                            "password_encrypted": encrypt_value(np_pass),
                        }
                    })
                    st.success(f"✅ Source privée ajoutée : {np_name}")
                    st.rerun()
                else:
                    st.error("Configurez d'abord ENCRYPTION_KEY.")
            else:
                st.warning("Tous les champs sont requis.")

    config["private_sources"] = private_sources


# ============================================
# TAB 4 : NEWSLETTERS
# ============================================
with tab4:
    st.header("Newsletters par email")
    st.info(
        "Configurez une boîte email dédiée où transférer vos newsletters juridiques. "
        "Le système les lira automatiquement et en extraira les articles."
    )

    config["newsletter_enabled"] = st.toggle(
        "Activer la collecte de newsletters",
        value=config.get("newsletter_enabled", False),
    )

    if config["newsletter_enabled"]:
        st.markdown("#### Configuration IMAP")
        st.caption("Les paramètres IMAP sont dans le fichier `.env` (IMAP_HOST, IMAP_USER, IMAP_PASSWORD).")

        st.markdown("#### Filtrer par expéditeur (optionnel)")
        st.caption("Laissez vide pour traiter tous les emails. Sinon, listez les adresses des newsletters à inclure.")

        senders = config.get("newsletter_senders", [])
        senders_text = st.text_area(
            "Adresses des newsletters (une par ligne)",
            value="\n".join(senders),
            height=150,
            placeholder=(
                "newsletter@dalloz.fr\n"
                "info@lexisnexis.fr\n"
                "newsletter@village-justice.com\n"
                "no-reply@legifrance.gouv.fr"
            ),
        )
        config["newsletter_senders"] = [
            s.strip() for s in senders_text.strip().split("\n") if s.strip()
        ]


# ============================================
# TAB 5 : ENVOI & TEST
# ============================================
with tab5:
    st.header("Envoi & Test")

    # Résumé config
    st.subheader("📊 Résumé de la configuration")
    col1, col2, col3 = st.columns(3)
    with col1:
        n_pub = len(config.get("public_sources", []))
        st.metric("Sources publiques", n_pub)
    with col2:
        n_priv = len(config.get("private_sources", []))
        st.metric("Sources privées", n_priv)
    with col3:
        nl = "✅ Activé" if config.get("newsletter_enabled") else "❌ Désactivé"
        st.metric("Newsletters", nl)

    st.divider()

    # Fréquence
    st.subheader("⏰ Fréquence")
    config["frequency"] = st.selectbox(
        "Fréquence du digest",
        ["weekly", "daily", "biweekly"],
        index=["weekly", "daily", "biweekly"].index(config.get("frequency", "weekly")),
        format_func=lambda x: {
            "weekly": "Hebdomadaire (lundi matin)",
            "daily": "Quotidien",
            "biweekly": "Bimensuel",
        }[x],
    )

    st.divider()

    # Sauvegarder
    col_save, col_test = st.columns(2)

    with col_save:
        if st.button("💾 Sauvegarder la configuration", type="primary", use_container_width=True):
            save_user_config(config)
            st.success("✅ Configuration sauvegardée !")

    with col_test:
        if st.button("🧪 Lancer un test (dry-run)", use_container_width=True):
            save_user_config(config)
            st.info("Lancement du pipeline en mode test...")
            st.code("python main.py --dry-run", language="bash")
            st.caption("Exécutez cette commande dans votre terminal pour tester le pipeline sans envoi email.")

    st.divider()

    # Aperçu du JSON
    with st.expander("🔍 Aperçu de la configuration (JSON)"):
        # Masquer les mots de passe
        display_config = json.loads(json.dumps(config))
        for src in display_config.get("private_sources", []):
            creds = src.get("credentials", {})
            if "password_encrypted" in creds:
                creds["password_encrypted"] = "***chiffré***"
        st.json(display_config)


# === Sidebar ===
with st.sidebar:
    st.markdown("### ⚖️ Outils")

    if st.button("📋 Exporter config JSON"):
        st.download_button(
            "Télécharger",
            data=json.dumps(config, indent=2, ensure_ascii=False),
            file_name="veille_config.json",
            mime="application/json",
        )

    st.divider()

    st.markdown("### 📖 Guide rapide")
    st.markdown("""
1. **Expertise** : décrivez vos domaines
2. **Sources publiques** : ajoutez RSS/sites
3. **Sources privées** : ajoutez vos accès
4. **Newsletters** : configurez le forwarding
5. **Sauvegardez** et testez !
""")

    st.divider()
    st.caption("Veille Juridique IA v1.0")
