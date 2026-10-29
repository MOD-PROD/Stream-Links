from http.server import BaseHTTPRequestHandler
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import json
import re
import time

GALTRO_URL = "https://galtro.xyz/m6grt87v4v8d7s/"
TIMEOUT = 12
MAX_WORKERS = 8
DELAY = 0.3

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Referer": "https://www.google.com/",
}

# Une annonce doit contenir au moins une de ces formulations.
ANNOUNCEMENT_RE = re.compile(
    r"\b(?:"
    r"devient|nouvelle\s+adresse|nouveau\s+domaine|"
    r"notre\s+nouvelle\s+adresse|adresse\s+officielle|"
    r"new\s+address|new\s+domain|is\s+now|now\s+at|"
    r"has\s+moved\s+to|moved\s+to|changed\s+(?:our\s+)?domain|"
    r"new\s+website|official\s+website|replaced\s+by"
    r")\b",
    re.IGNORECASE,
)

URL_RE = re.compile(
    r"(?:(?:https?://)?(?:www\.)?)"
    r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z]{2,}(?:/[^\s<>'\"\]\[()]*)?",
    re.IGNORECASE,
)


def safe_get(url):
    """GET tolérant aux erreurs réseau ; suit uniquement les redirections HTTP."""
    try:
        return requests.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
    except requests.RequestException:
        return None


def normalize_url(value, base_url=None):
    """Normalise une URL candidate et n'accepte que HTTP(S) avec un hostname."""
    if not value:
        return None

    value = value.strip().strip(" \t\r\n.,;:!?()[]{}<>\"'")
    if not value or value.startswith(("javascript:", "mailto:", "tel:", "#")):
        return None

    if value.startswith("//"):
        value = "https:" + value
    elif re.match(r"^https?://", value, re.IGNORECASE):
        pass
    elif base_url:
        value = urljoin(base_url, value)
    else:
        value = "https://" + value.lstrip("/")

    try:
        parsed = urlparse(value)
        if parsed.scheme.lower() not in ("http", "https"):
            return None
        if not parsed.hostname or "." not in parsed.hostname:
            return None
        if parsed.username or parsed.password:
            return None
        if any(ch.isspace() for ch in parsed.hostname):
            return None
        return parsed.geturl()
    except (TypeError, ValueError):
        return None


def domain_of(url):
    try:
        return (urlparse(url).hostname or "").lower().removeprefix("www.")
    except (TypeError, ValueError):
        return ""


def validate_announced_url(candidate, current_url):
    """
    Vérifie qu'une adresse annoncée répond réellement.
    En cas d'échec, ne remplace pas l'adresse actuelle.
    """
    candidate = normalize_url(candidate, current_url)
    if not candidate:
        return None

    # Évite de traiter comme un changement une URL du domaine actuel.
    if domain_of(candidate) == domain_of(current_url):
        return None

    response = safe_get(candidate)
    if not response or response.status_code >= 400:
        return None

    final_url = normalize_url(response.url)
    if not final_url:
        return None

    # On accepte la destination finale des redirections HTTP du nouveau domaine.
    return final_url


def extract_announced_url(soup, page_url):
    """
    Cherche une annonce de changement de domaine dans le texte visible.
    La destination est extraite d'abord des liens voisins de l'annonce,
    puis des URL présentes dans le texte de l'annonce.
    """
    page_text = soup.get_text(" ", strip=True)
    if not ANNOUNCEMENT_RE.search(page_text):
        return None

    current_domain = domain_of(page_url)

    # 1. Les liens placés dans le même bloc que l'annonce sont les plus fiables.
    for node in soup.find_all(string=ANNOUNCEMENT_RE):
        parent = node.parent
        for _ in range(4):
            if not parent or getattr(parent, "name", None) in ("html", "body"):
                break

            block_text = parent.get_text(" ", strip=True)
            if ANNOUNCEMENT_RE.search(block_text):
                for anchor in parent.find_all("a", href=True):
                    candidate = normalize_url(anchor.get("href", ""), page_url)
                    if candidate and domain_of(candidate) != current_domain:
                        checked = validate_announced_url(candidate, page_url)
                        if checked:
                            return checked

                # 2. Une adresse peut être écrite directement dans le texte.
                for match in URL_RE.finditer(block_text):
                    candidate = normalize_url(match.group(0), page_url)
                    if candidate and domain_of(candidate) != current_domain:
                        checked = validate_announced_url(candidate, page_url)
                        if checked:
                            return checked
            parent = parent.parent

    # 3. Dernier recours : URL dans la phrase/contenu de la page qui annonce
    # explicitement le changement. Le domaine courant est toujours exclu.
    for match in URL_RE.finditer(page_text):
        candidate = normalize_url(match.group(0), page_url)
        if candidate and domain_of(candidate) != current_domain:
            checked = validate_announced_url(candidate, page_url)
            if checked:
                return checked

    return None


def resolve_site(site):
    """
    Nouvelle logique :
    - suit les redirections HTTP normales ;
    - analyse la page d'arrivée pour détecter une annonce de changement ;
    - si une nouvelle adresse annoncée est trouvée et vérifiée, l'utilise ;
    - sinon conserve l'URL finale fonctionnelle.
    Aucun chemin /home/ n'est requis.
    """
    start_url = normalize_url(site.get("url"))
    if not start_url:
        return None, f"✗ {site.get('nom', 'Site')} : URL source invalide"

    response = safe_get(start_url)
    if not response:
        return None, f"✗ {site.get('nom', 'Site')} : page source inaccessible"

    if response.status_code >= 400:
        return None, (
            f"✗ {site.get('nom', 'Site')} : HTTP {response.status_code}"
        )

    current_url = normalize_url(response.url) or start_url
    content_type = response.headers.get("Content-Type", "").lower()

    if "html" in content_type or not content_type:
        soup = BeautifulSoup(response.text, "html.parser")
        announced_url = extract_announced_url(soup, current_url)

        if announced_url:
            result = {**site, "final_url": announced_url}
            return result, f"✓ {site['nom']} : nouvelle adresse détectée → {announced_url}"

    # Pas d'annonce fiable : on garde l'adresse finale qui a répondu.
    result = {**site, "final_url": current_url}
    if current_url != start_url:
        return result, f"✓ {site['nom']} : redirection HTTP → {current_url}"
    return result, f"✓ {site['nom']} : adresse active → {current_url}"


def scrape_galtro():
    """Récupère les sites listés dans l'annuaire configuré."""
    response = safe_get(GALTRO_URL)
    if not response or response.status_code >= 400:
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    sites = []

    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cols = row.find_all(["td", "th"])
            if not cols or all(col.name == "th" for col in cols):
                continue

            nom, url, desc = "", "", ""
            for col in cols:
                anchor = col.find("a", href=True)
                if anchor and not url:
                    candidate = normalize_url(anchor.get("href", ""), response.url)
                    if candidate:
                        url = candidate
                        nom = anchor.get_text(" ", strip=True)

                text = col.get_text(" ", strip=True)
                if text and not nom:
                    nom = text
                elif text and text != nom and not desc:
                    desc = text

            if url and nom:
                sites.append({"nom": nom, "url": url, "desc": desc[:120]})

    if not sites:
        for anchor in soup.find_all("a", href=True):
            href = normalize_url(anchor.get("href", ""), response.url)
            nom = anchor.get_text(" ", strip=True)
            if href and nom and len(nom) > 1:
                sites.append({"nom": nom, "url": href, "desc": ""})

    seen, unique = set(), []
    for site in sites:
        key = site["url"].rstrip("/").lower()
        if key not in seen:
            seen.add(key)
            unique.append(site)

    return unique


def get_all_sites():
    raw_sites = scrape_galtro()
    if not raw_sites:
        return {
            "error": "Impossible de récupérer les sites depuis galtro.xyz",
            "sites": [],
            "total": 0,
            "logs": [],
        }

    resolved = []
    logs = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(resolve_site, site): site
            for site in raw_sites
        }
        for future in as_completed(futures):
            site = futures[future]
            try:
                result, log_line = future.result()
            except Exception as exc:
                result = None
                log_line = f"✗ {site.get('nom', 'Site')} : erreur de résolution ({type(exc).__name__})"

            logs.append(log_line)
            if result:
                resolved.append(result)

    # Conserve l'ordre d'origine de l'annuaire.
    order = {site["url"]: index for index, site in enumerate(raw_sites)}
    resolved.sort(key=lambda item: order.get(item["url"], 999))

    # Déduplique les destinations finales.
    seen_urls, unique = set(), []
    for site in resolved:
        final_url = (site.get("final_url") or site["url"]).rstrip("/").lower()
        if final_url not in seen_urls:
            seen_urls.add(final_url)
            unique.append(site)

    return {"sites": unique, "total": len(unique), "logs": logs}


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        data = get_all_sites()
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "s-maxage=600")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    print(json.dumps(get_all_sites(), ensure_ascii=False, indent=2))
