import requests
from bs4 import BeautifulSoup
import re
from urllib.parse import urljoin, urlparse, quote_plus
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import BaseHTTPRequestHandler
import json

# ── CONFIG ────────────────────────────────────────────────────────────────────
SEARCH_QUERY = "alternatives galtro.xyz listes sites streaming redirection france 2026"
GOOGLE_URL = "https://www.google.com/search?q="
MAX_ANNUAIRES = 15
MAX_REDIRECTS = 12
TIMEOUT = 8
DELAY = 1.0
MAX_WORKERS = 8

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}

def safe_get(url, allow_redirects=True):
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=allow_redirects)
        r.raise_for_status()
        return r
    except Exception:
        return None

def is_functional(url):
    r = safe_get(url, allow_redirects=False)
    return r is not None and 200 <= r.status_code < 400

def find_annuaires(query):
    search_url = GOOGLE_URL + quote_plus(query)
    r = safe_get(search_url)
    if not r:
        return []
    soup = BeautifulSoup(r.text, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/url?q=" in href:
            m = re.search(r"/url\?q=([^&]+)", href)
            if m:
                real_url = requests.compat.unquote(m.group(1))
                if re.match(r"https?://(www\.)?[\w-]+\.(com|fr|net|org|xyz)/?", real_url) and not any(d in real_url for d in ["google", "quora", "youtube", "reddit", "similarweb"]):
                    links.append(real_url)
    return list(dict.fromkeys(links))[:MAX_ANNUAIRES]

def extract_redirection_links(annuaire_url):
    r = safe_get(annuaire_url)
    if not r:
        return []
    soup = BeautifulSoup(r.text, "html.parser")
    links = []
    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cols = row.find_all("td")
            if len(cols) >= 2:
                a = cols[1].find("a", href=True)
                if a and re.match(r"https?://[\w-]+\.com(/\S*)?\?u=\w+", a["href"]):
                    links.append(a["href"])
    for a in soup.find_all("a", href=True):
        href = urljoin(annuaire_url, a["href"])
        if re.match(r"https?://[\w-]+\.com(/\S*)?\?u=\w+", href):
            links.append(href)
    return list(dict.fromkeys(links))

def follow_to_home(start_url):
    current = start_url
    visited = set()
    for _ in range(MAX_REDIRECTS):
        if current in visited:
            return None
        visited.add(current)
        r = safe_get(current)
        if not r:
            return None
        current = r.url
        if '/home/' in urlparse(current).path.lower():
            return current
        soup = BeautifulSoup(r.text, "html.parser")
        meta = soup.find("meta", {"http-equiv": re.compile("refresh", re.I)})
        if meta:
            content = meta.get("content", "")
            m = re.search(r'url\s*=\s*([^;]+)', content, re.I)
            if m:
                current = urljoin(current, m.group(1).strip())
                time.sleep(DELAY)
                continue
        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True).upper()
            href = urljoin(current, a["href"])
            if '.COM' in text or 'DEVIENT' in text or 'ADRESSE' in text:
                current = href
                time.sleep(DELAY)
                break
        else:
            return None
    return None

def matches_pattern(url):
    if not url or '/home/' not in url.lower():
        return False
    parsed = urlparse(url)
    domain_without_com = parsed.netloc.split('.')[0].lower()
    path_parts = parsed.path.lower().rsplit('/', maxsplit=1)
    if len(path_parts) < 2:
        return False
    return path_parts[-1] == domain_without_com

def run_scraper():
    annuaire_urls = find_annuaires(SEARCH_QUERY)
    all_redir_links = []
    for ann in annuaire_urls:
        links = extract_redirection_links(ann)
        all_redir_links.extend(links)
    all_redir_links = list(dict.fromkeys(all_redir_links))

    home_urls = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(follow_to_home, link) for link in all_redir_links]
        for future in as_completed(futures):
            home = future.result()
            if home and matches_pattern(home) and is_functional(home):
                home_urls.append(home)

    return list(dict.fromkeys(home_urls))


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            links = run_scraper()
            result = {"links": links, "count": len(links)}
        except Exception as e:
            result = {"links": [], "count": 0, "error": str(e)}

        body = json.dumps(result).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass
