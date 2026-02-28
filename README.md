# 🎬 Stream Links — Streaming Explorer Engine

> Application web optimisée **grand écran / TV** qui découvre et affiche automatiquement les liens actifs de sites de streaming français, via un scraper Python côté serveur déployé sur Vercel.

![Dark Cinema UI](https://img.shields.io/badge/UI-Dark%20Cin%C3%A9ma-c9a84c?style=flat-square) ![Python](https://img.shields.io/badge/API-Python%203.x-3776AB?style=flat-square&logo=python) ![Vercel](https://img.shields.io/badge/Deploy-Vercel-000000?style=flat-square&logo=vercel) ![TV Ready](https://img.shields.io/badge/Optimis%C3%A9-TV%20%2F%20Grand%20%C3%A9cran-gold?style=flat-square)

---

## ✨ Fonctionnalités

- **10 tuiles cliquables** (2 rangées × 5) affichant les sites de streaming actifs
- **Scraper automatique** — trouve les liens fonctionnels via Google + annuaires + chaînes de redirections
- **Interface Dark Cinéma** — noir profond, accents dorés, grain filmique, typographie Bebas Neue
- **Optimisé TV** — grands éléments, navigation clavier (Tab/Entrée), aucun scroll requis
- **Skeleton loader** + indicateur de statut en temps réel
- **Fallback hors ligne** si le scraper ne retourne rien

---

## 🧠 Comment ça marche

```
Utilisateur ouvre l'app
        ↓
Frontend appelle /api/links
        ↓
Scraper Python (Vercel Serverless) :
  1. Recherche Google → annuaires de liens streaming
  2. Visite chaque annuaire → extrait liens de redirection (?u=xxxxx)
  3. Suit chaque chaîne → trouve l'URL finale /home/
  4. Vérifie que le lien répond (HTTP 200)
        ↓
Renvoie les 10 premiers liens valides
        ↓
Frontend affiche les tuiles cliquables
```

---

## 📁 Structure du projet

```
stream-links/
├── public/
│   └── index.html        ← Interface TV (HTML/CSS/JS vanilla)
├── api/
│   └── links.py          ← Scraper Python (Vercel Serverless Function)
├── requirements.txt      ← Dépendances Python (requests, beautifulsoup4)
├── vercel.json           ← Configuration Vercel (routes + builds)
└── README.md
```

---

## 🚀 Déploiement sur Vercel

### Option A — Via GitHub (recommandé)

1. **Fork ou clone** ce repo sur ton compte GitHub
2. Va sur [vercel.com](https://vercel.com) → **New Project**
3. Importe le repo GitHub
4. Laisse les paramètres par défaut → **Deploy**

Vercel détecte automatiquement `vercel.json` et configure tout.

### Option B — Via CLI

```bash
# Installer Vercel CLI
npm i -g vercel

# Déployer
cd stream-links
vercel
```

Répondre aux prompts :
- **Set up and deploy** → `Y`
- **Project name** → `stream-links` (ou autre)
- **Framework** → `Other`
- **Root directory** → `./`

---

## 💻 Lancer en local

```bash
# Cloner le repo
git clone https://github.com/TON_USERNAME/stream-links.git
cd stream-links

# Installer les dépendances Python
pip install -r requirements.txt

# Tester le scraper directement
python api/links.py

# Pour le frontend, ouvrir simplement public/index.html dans un navigateur
# (l'API ne fonctionnera pas en local sans Vercel Dev)
```

Pour tester l'API en local avec Vercel Dev :
```bash
npm i -g vercel
vercel dev
```

---

## ⚙️ Configuration

Dans `api/links.py`, tu peux modifier :

| Variable | Défaut | Description |
|---|---|---|
| `SEARCH_QUERY` | `"alternatives galtro.xyz..."` | Requête Google pour trouver les annuaires |
| `MAX_ANNUAIRES` | `15` | Nombre max d'annuaires à visiter |
| `MAX_REDIRECTS` | `12` | Profondeur max de la chaîne de redirections |
| `TIMEOUT` | `8s` | Timeout par requête HTTP |
| `MAX_WORKERS` | `8` | Threads parallèles pour le suivi des liens |

---

## ⚠️ Limites connues

- **Timeout Vercel** : le scraper peut prendre 30–60s. Plan gratuit = 60s max, plan Pro = 300s.
- **Google blocking** : Google peut bloquer les requêtes depuis les IPs de datacenter Vercel. Dans ce cas, l'app passe en mode hors ligne avec des liens placeholder.
- **Solution recommandée** : pour un usage fréquent, exécuter le scraper en local et alimenter un cache (Vercel KV / Redis) que le frontend interroge.

---

## 🎨 Design

| Élément | Valeur |
|---|---|
| Thème | Dark Cinéma |
| Couleur principale | `#080a0e` (noir profond) |
| Accent | `#c9a84c` (or) |
| Police titre | Bebas Neue |
| Police UI | Outfit |
| Effets | Grain filmique, scanlines, vignette |

---

## 📄 Licence

MIT — libre d'utilisation, modification et distribution.
