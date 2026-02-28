from http.server import BaseHTTPRequestHandler
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import requests, json, re
from concurrent.futures import ThreadPoolExecutor, as_completed

GALTRO_URL    = "https://galtro.xyz/m6grt87v4v8d7s/"
MAX_REDIRECTS = 12
TIMEOUT       = 10
MAX_WORKERS   = 8

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}

def safe_get(url):
    try:
        return requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
    except Exception:
        return None

def matches_pattern(url):
    """
    Vérifie le pattern du script original :
    URL contient /home/ ET la dernière partie du path == nom de domaine sans .com
    ex: https://wiflix.com/home/wiflix
    """
    if not url or '/home/' not in url.lower():
        return False
    try:
        parsed = urlparse(url)
        domain_root = parsed.netloc.split('.')[0].lower()
        last_part = parsed.path.rstrip('/').rsplit('/', 1)[-1].lower()
        return last_part == domain_root
    except Exception:
        return False

def follow_to_home(start_url):
    """Suit la chaîne de redirections pour trouver l'URL finale /home/domain."""
    current = start_url
    visited = set()

    for _ in range(MAX_REDIRECTS):
        if not current or current in visited:
            return None
        visited.add(current)

        resp = safe_get(current)
        if not resp:
            return None

        current = resp.url  # suit les redirections HTTP 3xx

        if matches_pattern(current):
            return current

        soup = BeautifulSoup(resp.text, "html.parser")

        # meta refresh
        meta = soup.find("meta", attrs={"http-equiv": re.compile("refresh", re.I)})
        if meta and meta.get("content"):
            m = re.search(r'url=["\']?([^"\';\s>]+)', meta["content"], re.I)
            if m:
                next_url = urljoin(current, m.group(1))
                if next_url not in visited:
                    current = next_url
                    continue

        # Liens textuels de navigation
        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True).upper()
            href = urljoin(current, a["href"])
            if any(kw in text for kw in ['.COM', 'DEVIENT', 'ADRESSE', 'ENTRER', 'ACCEDER', 'HOME', 'ENTER']):
                if href not in visited:
                    current = href
                    break
        else:
            return None

    return None

def scrape_galtro():
    """Scrape galtro.xyz et retourne la liste des sites avec leurs URLs de redirection."""
    resp = safe_get(GALTRO_URL)
    if not resp:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    sites = []

    # Cherche dans les tableaux
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
                        url  = href
                        nom  = a_tag.get_text(strip=True)
                text = col.get_text(strip=True)
                if text and not nom:
                    nom = text
                elif text and text != nom and not desc:
                    desc = text
            if url and nom:
                sites.append({"nom": nom, "url": url, "desc": desc[:120]})

    # Fallback liens libres
    if not sites:
        for a in soup.find_all("a", href=True):
            href = a.get("href", "").strip()
            nom  = a.get_text(strip=True)
            if href.startswith("http") and nom and len(nom) > 1:
                sites.append({"nom": nom, "url": href, "desc": ""})

    # Dédoublonner
    seen, unique = set(), []
    for s in sites:
        if s["url"] not in seen:
            seen.add(s["url"])
            unique.append(s)
    return unique

def get_all_sites():
    raw = scrape_galtro()
    if not raw:
        return {"error": "Impossible de scraper galtro.xyz", "sites": []}

    resolved = []
    logs = []

    def resolve(site):
        final = follow_to_home(site["url"])
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
