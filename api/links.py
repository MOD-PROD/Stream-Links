from http.server import BaseHTTPRequestHandler
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import requests, json, re, time
from concurrent.futures import ThreadPoolExecutor, as_completed

GALTRO_URL    = "https://galtro.xyz/m6grt87v4v8d7s/"
MAX_REDIRECTS = 25
TIMEOUT       = 12
MAX_WORKERS   = 8
DELAY         = 0.3

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
    Pattern accepté :
      https://batiav.com/home/batiav
      https://batiav.com/4k2qyb4h7g44/home/batiav  ← segment aléatoire avant /home/
    Condition : path contient /home/ ET segment APRES /home/ == nom de domaine
    """
    if not url or '/home/' not in url.lower():
        return False
    try:
        parsed = urlparse(url)
        name   = parsed.netloc.lower().replace('www.', '').split('.')[0]
        m = re.search(r'/home/([^/?#]+)', parsed.path.lower())
        if not m:
            return False
        return m.group(1).rstrip('/') == name
    except Exception:
        return False

def pick_next_link(soup, current_url, visited):
    """
    Chaque page intermédiaire ne contient qu'un seul lien cliquable (case/image).
    On prend simplement le premier lien <a> valide non déjà visité.
    Priorité au lien qui matche déjà le pattern final.
    """
    for a in soup.find_all("a", href=True):
        raw = a["href"].strip()
        if not raw or raw.startswith("#") or raw.startswith("javascript"):
            continue
        href = urljoin(current_url, raw)
        if href in visited:
            continue
        # Si ce lien est déjà la cible finale, retourne immédiatement
        if matches_target(href):
            return href
        return href  # sinon prend le premier lien disponible

    return None

def follow_chain(start_url):
    """
    Suit toute la chaîne de redirections jusqu'au pattern /home/nom
    """
    current = start_url
    visited = set()

    for step in range(MAX_REDIRECTS):
        if not current or current in visited:
            return None
        visited.add(current)

        resp = safe_get(current)
        if not resp:
            return None

        # URL après redirections HTTP 3xx
        current = resp.url

        if matches_target(current):
            return current

        soup = BeautifulSoup(resp.text, "html.parser")

        # meta refresh
        meta = soup.find("meta", attrs={"http-equiv": re.compile("refresh", re.I)})
        if meta and meta.get("content"):
            m = re.search(r'url=["\']?([^"\';\s>]+)', meta["content"], re.I)
            if m:
                nxt = urljoin(current, m.group(1).strip())
                if matches_target(nxt):
                    return nxt
                if nxt not in visited:
                    current = nxt
                    time.sleep(DELAY)
                    continue

        # Cherche le prochain lien
        nxt = pick_next_link(soup, current, visited)
        if nxt:
            current = nxt
            time.sleep(DELAY)
        else:
            # Aucun lien trouvé — retourne si ça matche, sinon None
            return current if matches_target(current) else None

    return None

def scrape_galtro():
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

    order = {s["url"]: i for i, s in enumerate(raw)}
    resolved.sort(key=lambda s: order.get(s["url"], 999))

    # Dédoublonnage par URL finale
    seen_urls, unique = set(), []
    for s in resolved:
        final = s.get("final_url", s["url"]).rstrip("/").lower().split("?")[0]
        if final not in seen_urls:
            seen_urls.add(final)
            unique.append(s)

    return {"sites": unique, "total": len(unique), "logs": logs}

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
