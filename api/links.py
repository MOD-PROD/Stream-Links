from http.server import BaseHTTPRequestHandler
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import requests, json, re, time
from concurrent.futures import ThreadPoolExecutor, as_completed

GALTRO_URL    = "https://galtro.xyz/m6grt87v4v8d7s/"
MAX_REDIRECTS = 20
TIMEOUT       = 12
MAX_WORKERS   = 8
DELAY         = 0.5

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Referer": "https://www.google.com/",
}

def safe_get(url):
    try:
        return requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
    except Exception:
        return None

def matches_target(url):
    """
    Pattern final recherché : URL contient /home/
    ET le dernier segment du path == nom de domaine sans extension
    ex: https://wiflix.com/home/wiflix  ✓
        https://batiav.com/home/batiav  ✓
    """
    if not url or '/home/' not in url.lower():
        return False
    try:
        parsed   = urlparse(url)
        domain   = parsed.netloc.lower()
        # enlève www. et prend juste le nom (avant le premier point)
        name     = domain.replace('www.', '').split('.')[0]
        # dernier segment du path
        last_seg = parsed.path.rstrip('/').rsplit('/', 1)[-1].lower()
        return last_seg == name
    except Exception:
        return False

def follow_chain(start_url):
    """
    Suit toute la chaîne de redirections (HTTP 3xx + meta-refresh + liens page)
    jusqu'à trouver une URL qui correspond au pattern /home/nomsite
    ou jusqu'à MAX_REDIRECTS étapes.
    Retourne l'URL cible ou None.
    """
    current = start_url
    visited = set()

    for step in range(MAX_REDIRECTS):
        if not current or current in visited:
            return None
        visited.add(current)

        # — requête (requests suit déjà les 3xx automatiquement) —
        resp = safe_get(current)
        if not resp:
            return None

        # URL après redirections HTTP
        current = resp.url

        # Vérifie si on est arrivé
        if matches_target(current):
            return current

        soup = BeautifulSoup(resp.text, "html.parser")

        # — meta refresh —
        meta = soup.find("meta", attrs={"http-equiv": re.compile("refresh", re.I)})
        if meta and meta.get("content"):
            m = re.search(r'url=["\']?([^"\';\s>]+)', meta["content"], re.I)
            if m:
                nxt = urljoin(current, m.group(1).strip())
                if nxt not in visited:
                    if matches_target(nxt):
                        return nxt
                    current = nxt
                    time.sleep(DELAY)
                    continue

        # — cherche TOUS les liens <a> de la page, prend le premier pertinent —
        next_url = None

        # Priorité 1 : lien qui contient déjà /home/
        for a in soup.find_all("a", href=True):
            href = urljoin(current, a["href"].strip())
            if '/home/' in href.lower():
                if matches_target(href):
                    return href
                if href not in visited:
                    next_url = href
                    break

        # Priorité 2 : lien avec texte d'action ou paramètre ?u=
        if not next_url:
            for a in soup.find_all("a", href=True):
                text = a.get_text(strip=True).lower()
                href = urljoin(current, a["href"].strip())
                raw  = a["href"]
                if (any(kw in text for kw in ["entrer", "accéder", "enter", "accueil",
                                               "home", "go", "watch", "voir", "start",
                                               "continuer", "nouveau", "new", "site"])
                        or "?u=" in raw or re.search(r'\?u=\w+', raw)):
                    if href not in visited and href != current:
                        next_url = href
                        break

        # Priorité 3 : premier lien externe (autre domaine)
        if not next_url:
            current_host = urlparse(current).netloc
            for a in soup.find_all("a", href=True):
                href = urljoin(current, a["href"].strip())
                if urlparse(href).netloc != current_host and href not in visited:
                    next_url = href
                    break

        if next_url:
            current = next_url
            time.sleep(DELAY)
        else:
            # Rien à suivre → fin de chaîne, on retourne l'URL courante si elle matche
            return current if matches_target(current) else None

    return None

def scrape_galtro():
    """Scrape galtro.xyz, retourne liste de {nom, url, desc}."""
    resp = safe_get(GALTRO_URL)
    if not resp:
        return []

    soup  = BeautifulSoup(resp.text, "html.parser")
    sites = []

    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cols = row.find_all(["td", "th"])
            if not cols or all(c.name == "th" for c in cols):
                continue
            nom, url, desc = "", "", ""
            for col in cols:
                a_tag = col.find("a", href=True)
                if a_tag and not url:
                    href = a_tag.get("href", "").strip()
                    if href.startswith("http"):
                        url = href
                        nom = a_tag.get_text(strip=True)
                text = col.get_text(strip=True)
                if text and not nom:
                    nom = text
                elif text and text != nom and not desc:
                    desc = text
            if url and nom:
                sites.append({"nom": nom, "url": url, "desc": desc[:120]})

    # Fallback : tous les liens <a>
    if not sites:
        for a in soup.find_all("a", href=True):
            href = a.get("href", "").strip()
            nom  = a.get_text(strip=True)
            if href.startswith("http") and nom and len(nom) > 1:
                sites.append({"nom": nom, "url": href, "desc": ""})

    seen, unique = set(), []
    for s in sites:
        if s["url"] not in seen:
            seen.add(s["url"])
            unique.append(s)
    return unique

def get_all_sites():
    raw = scrape_galtro()
    if not raw:
        return {"error": "Impossible de scraper galtro.xyz", "sites": [], "logs": []}

    resolved = []
    logs     = []

    def resolve(site):
        final = follow_chain(site["url"])
        if final:
            logs.append(f"✓ {site['nom']} → {final}")
            return {**site, "final_url": final}
        else:
            logs.append(f"✗ {site['nom']} : aucune URL /home/ trouvée")
            return None

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(resolve, s): s for s in raw}
        for future in as_completed(futures):
            result = future.result()
            if result:
                resolved.append(result)

    # Remettre dans l'ordre original
    order = {s["url"]: i for i, s in enumerate(raw)}
    resolved.sort(key=lambda s: order.get(s["url"], 999))

    return {"sites": resolved, "total": len(resolved), "logs": logs}

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "s-maxage=600")
        self.end_headers()
        data = get_all_sites()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

    def log_message(self, format, *args):
        pass
