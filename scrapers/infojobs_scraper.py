# scrapers/infojobs_scraper.py
import time
import argparse
import re
import os, subprocess
import requests
import json
import random
import sys

from typing import Dict, List, Optional
from urllib.parse import quote
from datetime import datetime, timedelta, date
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.action_chains import ActionChains
from webdriver_manager.chrome import ChromeDriverManager

try:
    from zoneinfo import ZoneInfo 
except Exception:
    ZoneInfo = None

import psycopg2  

# 🔴 COLE SUA CONNECTION STRING AQUI (ou use variável de ambiente SUPABASE_CONN)
CONNECTION_STRING = os.getenv(
    "SUPABASE_CONN",
    "postgresql://postgres.wnhqaiogzvvwrxcgfwsj:abkm@aws-1-sa-east-1.pooler.supabase.com:5432/postgres"
)

# ---------------------- Helpers de conexão/limpeza -------------------------
def conectar_banco():
    """Conecta ao banco PostgreSQL do Supabase"""
    try:
        conn = psycopg2.connect(CONNECTION_STRING)
        print("✅ Conectado ao Supabase com sucesso!")
        return conn
    except Exception as e:
        print(f"❌ Erro na conexão: {e}")
        return None

def _none_if_nullish(v):
    """Converte 'NULL'/'', whitespace -> None (para gravar como SQL NULL)."""
    if v is None:
        return None
    s = str(v).strip()
    if not s or s.upper() == "NULL":
        return None
    return s

def _prep_row_for_db(d):
    cols = [
        "titulo_vaga", "empresa", "localizacao", "salario", "descricao",
        "requisitos", "beneficios", "tipo_contrato", "modalidade",
        "data_publicacao", "url_vaga", "fonte"
    ]
    out = {k: _none_if_nullish(d.get(k)) for k in cols}
    out["fonte"] = "Infojobs.com.br"

    dp = out.get("data_publicacao")
    # Se vier "YYYY-MM-DD", transforma em date do Python
    if isinstance(dp, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", dp):
        try:
            out["data_publicacao"] = datetime.strptime(dp, "%Y-%m-%d").date()
        except Exception:
            pass

    return out


#----------------------- Salvamento em lotes + verificação -----------------
def salvar_vagas_supabase(conn, vagas, lote_size=50):
    """Salva as vagas no Supabase em lotes com tratamento de duplicatas."""
    if not vagas:
        print("⚠️  Nenhuma vaga para salvar")
        return conn

    sql_insert = """
    INSERT INTO vagas_emprego (
        titulo_vaga, empresa, localizacao, salario, descricao,
        requisitos, beneficios, tipo_contrato, modalidade,
        data_publicacao, url_vaga, fonte
    ) VALUES (
        %(titulo_vaga)s, %(empresa)s, %(localizacao)s, %(salario)s, %(descricao)s,
        %(requisitos)s, %(beneficios)s, %(tipo_contrato)s, %(modalidade)s,
        %(data_publicacao)s, %(url_vaga)s, %(fonte)s
    )
    ON CONFLICT (url_vaga) DO NOTHING;
    """

    sql_check = "SELECT COUNT(*) FROM vagas_emprego WHERE url_vaga = %s;"

    vagas_salvas = 0
    vagas_duplicadas = 0
    vagas_erro = 0

    print(f"💾 Processando {len(vagas)} vagas em lotes de {lote_size}...")

    for i, vaga in enumerate(vagas, 1):
        try:
            if conn.closed:
                print("  🔄 Reconectando ao banco...")
                conn = conectar_banco()
                if not conn:
                    print("  ❌ Não foi possível reconectar")
                    return conn

            cursor = conn.cursor()

            # checa duplicata
            cursor.execute(sql_check, (vaga['url_vaga'],))
            existe = cursor.fetchone()[0] > 0
            if existe:
                vagas_duplicadas += 1
                print(f"  🔄 ({i}/{len(vagas)}) Vaga já existe: {vaga['titulo_vaga']}")
                cursor.close()
                continue

            # insere
            cursor.execute(sql_insert, vaga)

            if cursor.rowcount > 0:
                vagas_salvas += 1
                print(f"  ✅ ({i}/{len(vagas)}) Nova vaga salva: {vaga['titulo_vaga']}")
            else:
                vagas_duplicadas += 1

            cursor.close()

            # commit por lote
            if i % lote_size == 0 or i == len(vagas):
                conn.commit()
                print(f"  💾 Commit realizado ({i}/{len(vagas)})")

        except psycopg2.OperationalError as e:
            print(f"  ⚠️ Erro de conexão: {e}")
            print("  🔄 Tentando reconectar...")
            try:
                conn = conectar_banco()
                if conn:
                    print("  ✅ Reconectado com sucesso")
                    cursor = conn.cursor()
                    cursor.execute(sql_insert, vaga)
                    conn.commit()
                    cursor.close()
                    vagas_salvas += 1
                    print(f"  ✅ Vaga salva após reconexão")
                else:
                    vagas_erro += 1
            except Exception:
                vagas_erro += 1

        except Exception as e:
            print(f"  ❌ ({i}/{len(vagas)}) Erro ao salvar '{vaga.get('titulo_vaga','')[:50]}...': {str(e)[:100]}")
            vagas_erro += 1
            try:
                conn.rollback()
            except:
                pass

    try:
        conn.commit()
    except:
        pass

    print(f"\n✅ RESULTADO DO SALVAMENTO:")
    print(f"   📊 Vagas novas salvas: {vagas_salvas}")
    print(f"   🔄 Vagas duplicadas ignoradas: {vagas_duplicadas}")
    if vagas_erro > 0:
        print(f"   ❌ Vagas com erro: {vagas_erro}")
    print(f"   📈 Total processadas: {len(vagas)}")

    return conn


def verificar_vagas_salvas(conn):
    """Mostra estatísticas básicas (mesmo formato da Bruna)."""
    try:
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM vagas_emprego;")
        total_geral = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM vagas_emprego WHERE fonte = 'Infojobs.com.br';")
        total_infojobs = cursor.fetchone()[0]

        cursor.execute("""
            SELECT titulo_vaga, empresa, localizacao, modalidade, data_coleta
            FROM vagas_emprego
            WHERE fonte = 'Infojobs.com.br'
            ORDER BY data_coleta DESC
            LIMIT 5;
        """)
        ultimas_vagas = cursor.fetchall()

        print(f"\n📊 ESTATÍSTICAS DO BANCO:")
        print(f"   Total de vagas (geral): {total_geral}")
        print(f"   Total do InfoJobs: {total_infojobs}")

        if ultimas_vagas:
            print(f"\n📋 Últimas 5 vagas do InfoJobs:")
            for vaga in ultimas_vagas:
                print(f"   • {vaga[0]} - {vaga[1]} ({vaga[2]}) - {vaga[3]}")

        cursor.close()
    except Exception as e:
        print(f"❌ Erro ao verificar vagas salvas: {e}")


# ---------------------- Palavras-chave padrão (foco TI) --------------------
PYTHON_KEYWORDS = [
     # === DESENVOLVIMENTO ===
    "Desenvolvedor Python", "Desenvolvedor Java", "Desenvolvedor JavaScript", "Desenvolvedor Node",
    "Desenvolvedor Node.js", "Desenvolvedor React", "Desenvolvedor Angular", "Desenvolvedor Full Stack",
    "Desenvolvedor Full-Stack", "Desenvolvedor Backend", "Desenvolvedor Back-end", "Desenvolvedor Frontend",
    "Desenvolvedor Front-end","Desenvolvedor Mobile", "Desenvolvedor Android", "Desenvolvedor iOS", 
    "Engenheiro de Software", "Software Engineer",

    # === DADOS & IA ===
    "Cientista de Dados", "Data Scientist", "Analista de Dados", "Data Analyst", "Engenheiro de Dados", 
    "Data Engineer", "Engenheiro de Machine Learning", "Machine Learning Engineer", "Especialista em Inteligência Artificial",
    "Engenheiro de IA",

    # === BI & ANALYTICS ===
    "Analista de BI", "Analista de Business Intelligence", "Especialista em Power BI", "Analista de Power BI",
    "Engenheiro de BI",

    # === INFRA & CLOUD ===
    "DevOps", "Engenheiro DevOps", "DevOps Engineer", "Engenheiro de Cloud", "Cloud Engineer", "Arquiteto de Cloud",
    "Arquiteto AWS", "Arquiteto Azure", "Arquiteto GCP",

    # === BANCO DE DADOS ===
    "Administrador de Banco de Dados", "DBA", "Administrador de SQL", "Engenheiro de Banco de Dados",

    # === OUTROS ESPECIALIZADOS ===
    "Arquiteto de Software", "Tech Lead", "Product Owner Técnico", "Scrum Master Técnico",
    "QA Engineer", "Tester Automatizado",
]

# ------------------------ LLM (Groq) ------------------------
USE_LLM = False
LLM_ONLY_MODE = False
DEBUG_LLM = True  
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_FALLBACK_MODELS = [
    "llama-3.1-8b-instant",
    "groq/compound-mini",
]

# -------------------------- HELPERS --------------------------
def contains_keywords(text: str, keywords: List[str]) -> bool:
    """Retorna True se qualquer keyword aparecer no texto (case-insensitive)."""
    if not keywords:
        return True
    t = (text or "").lower()
    return any(k.lower() in t for k in keywords)

def _text(node):
    return node.get_text(" ", strip=True) if node else None

def extract_section_list(soup, title_regex: str):
    """Pega lista (ul>li) logo após um título tipo 'Exigências' / 'Benefícios'."""
    title = soup.find("div", class_="h4", string=re.compile(title_regex, re.I))
    if not title:
        return None
    ul = title.find_next("ul")
    if not ul:
        return None
    items = [_text(li) for li in ul.select("li") if _text(li)]
    return "; ".join(items) if items else None

def llm_extract_req_benef(descricao: str) -> dict:
    def _empty():
        return {"requisitos": [], "beneficios": []}

    if not descricao or len(descricao.strip()) < 40:
        return _empty()
    if not GROQ_API_KEY:
        return _empty()

    prompt = f"""
    Você é um assistente que EXTRAI dados estruturados de descrições de vagas.

    TAREFA:
    - Ler a descrição completa (PT-BR).
    - Extrair apenas o que ESTÁ ESCRITO em duas listas:
      "requisitos": hard/soft skills, formações, experiências, certificações, idiomas.
      "beneficios": VA/VR/VT, assistência médica/odontológica, PLR, gym, etc.
    - NÃO invente. NÃO inclua salários.
    - Responda SOMENTE JSON válido:

    {{
      "requisitos": ["..."],
      "beneficios": ["..."]
    }}

    DESCRIÇÃO:
    <<<
    {descricao}
    >>>
    """.strip()

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    model_candidates = [GROQ_MODEL] + [m for m in GROQ_FALLBACK_MODELS if m != GROQ_MODEL]

    for model_name in model_candidates:
        body = {
            "model": model_name,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": "Extraia fielmente; não invente; responda SOMENTE JSON."},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 600,
        }

        try:
            if DEBUG_LLM:
                print(f"[LLM] Chamando Groq… (modelo={model_name})")
            resp = requests.post(GROQ_URL, headers=headers, json=body, timeout=60)

            if resp.status_code != 200:
                if DEBUG_LLM:
                    print(f"[LLM] HTTP {resp.status_code}: {resp.text[:500]}")
                # Erros que justificam tentar o próximo modelo
                try:
                    err = resp.json().get("error", {})
                    code = (err.get("code") or "").lower()
                except Exception:
                    code = ""
                if code in {"model_decommissioned", "model_not_found", "model_not_available"}:
                    continue  # tenta próximo
                return _empty()

            content = resp.json()["choices"][0]["message"]["content"]
            data = json.loads(content)
            req = [x.strip() for x in data.get("requisitos", []) if isinstance(x, str) and x.strip()]
            ben = [x.strip() for x in data.get("beneficios", []) if isinstance(x, str) and x.strip()]
            return {"requisitos": req, "beneficios": ben}

        except Exception as e:
            if DEBUG_LLM:
                print(f"[LLM] Exceção: {e}")
            # tenta próximo candidato
            continue

    # se todos falharem
    return _empty()

def _normalize_pub_date(raw: Optional[str]) -> Optional[str]:
    """
    Converte datas de publicação em PT-BR para 'YYYY-MM-DD'.
    Suporta: 'Hoje', 'Ontem', 'há X dias/horas', '04/10/2025',
             '16 out', '16 out 2025', '16 outubro 2025',
             '16 de out de 2025', '2025-10-16', etc.
    """
    if not raw:
        return None

    txt = re.sub(r"\s+", " ", raw.strip().lower())
    # remove ruídos comuns
    txt = re.sub(r"\b(publicad[oa]s?|atualizad[oa]s?|em)\b", " ", txt)
    txt = txt.replace(",", " ")
    txt = re.sub(r"\s{2,}", " ", txt).strip()

    tz = ZoneInfo("America/Sao_Paulo") if ZoneInfo else None
    now = datetime.now(tz) if tz else datetime.now()
    today = now.date()

    # casos relativos
    if "hoje" in txt:
        return today.isoformat()
    if "ontem" in txt:
        return (today - timedelta(days=1)).isoformat()

    m = re.search(r"\bh[aá]\s+(\d+)\s*dias?\b", txt)
    if m:
        dias = int(m.group(1))
        return (today - timedelta(days=dias)).isoformat()

    m = re.search(r"\bh[aá]\s+(\d+)\s*horas?\b", txt)
    if m:
        horas = int(m.group(1))
        return (now - timedelta(hours=horas)).date().isoformat()

    # já em ISO
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", txt)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

    # dd/mm/yyyy
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", txt)
    if m:
        d, mo, y = map(int, m.groups())
        try:
            return date(y, mo, d).isoformat()
        except Exception:
            return None

    # mapa de meses PT-BR
    meses = {
        "jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
        "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12,
        "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4,
        "maio": 5, "junho": 6, "julho": 7, "agosto": 8, "setembro": 9,
        "outubro": 10, "novembro": 11, "dezembro": 12
    }

    # “dd mmm yyyy” ou “dd de mmm de yyyy”
    txt2 = re.sub(r"\bde\b", " ", txt)
    m = re.search(r"\b(\d{1,2})\s+([a-zç]+)\s+(\d{4})\b", txt2)
    if m:
        d = int(m.group(1))
        mon = meses.get(m.group(2)[:3], meses.get(m.group(2)))
        y = int(m.group(3))
        if mon:
            try:
                return date(y, mon, d).isoformat()
            except Exception:
                return None

    # “dd mmm” (sem ano) – ex.: “16 out”
    m = re.search(r"\b(\d{1,2})\s+([a-zç]{3,})\b", txt2)
    if m:
        d = int(m.group(1))
        mon = meses.get(m.group(2)[:3], meses.get(m.group(2)))
        if mon:
            # assume ano corrente; se a data ficar "no futuro" (> hoje + 3 dias), usa ano passado
            y = today.year
            try_date = date(y, mon, d)
            if try_date > (today + timedelta(days=3)):
                y -= 1
            try:
                return date(y, mon, d).isoformat()
            except Exception:
                return None

    # tentativas finais
    for fmt in ("%d %b %Y", "%d %B %Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(txt2, fmt).date().isoformat()
        except Exception:
            pass

    return None

# -------------------------- classe principal --------------------------
class InfoJobsScraper:
    def __init__(self, term: str, city_slug: Optional[str], headless: bool = True, target_links: int = 12):
        self.term = term
        self.city_slug = city_slug
        self.target_links = max(1, target_links)  
        self._headless = headless
        self.driver = self._make_driver(headless=headless)
        # timeouts globais do driver
        try:
            self.driver.set_page_load_timeout(35)   # tempo máximo p/ carregar página
            self.driver.set_script_timeout(30)
        except Exception:
            pass

    # ---- navegação / setup
    @staticmethod
    def _make_driver(headless: bool = True) -> webdriver.Chrome:
        chrome_options = Options()
        if headless:
            chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1366,768")
        chrome_options.add_argument("--lang=pt-BR")
        chrome_options.add_argument("--disable-quic")
        chrome_options.add_argument("--blink-settings=imagesEnabled=false")
        chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")
        chrome_options.add_argument("--ignore-certificate-errors")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
        chrome_options.add_experimental_option("useAutomationExtension", False)
        
        chrome_options.page_load_strategy = "none"  

        # manda os logs do chromedriver para o /dev/null (Windows: NUL)
        devnull = subprocess.DEVNULL
        service = Service(ChromeDriverManager().install(), log_output=devnull)

        return webdriver.Chrome(service=service, options=chrome_options)

    def _restart_browser(self):
        try:
            self.driver.quit()
        except Exception:
            pass
        # reabre mantendo o mesmo headless e janela
        # (se quiser, guarde os flags na __init__)
        self.driver = self._make_driver(headless=self._headless)
        try:
            self.driver.set_page_load_timeout(35)
            self.driver.set_script_timeout(30)
        except Exception:
            pass

    def _safe_get(self, url: str, max_retries: int = 3) -> None:
        for attempt in range(max_retries):
            try:
                self.driver.get(url)
                WebDriverWait(self.driver, 15).until(
                    lambda d: d.execute_script("return document.readyState") in ("interactive", "complete")
                )
                return
            except Exception as e:
                print(f"[ERRO] Tentativa {attempt+1}/{max_retries} falhou: {e}")
                if attempt < max_retries - 1:
                    time.sleep(random.uniform(3, 7))
                    self._restart_browser()  # opcional
                else:
                    raise

    @staticmethod
    def _build_list_url(term: str, city_slug: Optional[str], page: int = 1,
                        re_param: Optional[int] = None, idw: Optional[int] = None, isr: Optional[int] = None) -> str:
        term_slug = quote(term.lower().strip().replace(" ", "-"))
        if city_slug:
            base = f"https://www.infojobs.com.br/vagas-de-emprego-{term_slug}-em-{city_slug}.aspx"
        else:
            base = f"https://www.infojobs.com.br/vagas-de-emprego-{term_slug}.aspx"
        params = []
        if re_param:
            params.append(f"Antiguedad={re_param}")
        if idw:
            params.append(f"idw={idw}")
        if isr:
            params.append(f"isr={isr}")
        if page and page > 1:
            params.append(f"PageNumber={page}")
        return base + (("?" + "&".join(params)) if params else "")

    @staticmethod
    def _wait_and_accept_cookies(driver, timeout: int = 15):
        candidates = [
            (By.ID, "onetrust-accept-btn-handler"),
            (By.CSS_SELECTOR, "button#onetrust-accept-btn-handler"),
            (By.XPATH, "//button[contains(., 'Aceitar')]"),
            (By.XPATH, "//button[contains(., 'Concordo')]"),
            (By.CSS_SELECTOR, "button[aria-label*='Aceitar' i]"),
        ]
        for by, sel in candidates:
            try:
                btn = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((by, sel)))
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
                time.sleep(0.2)
                try:
                    btn.click()
                except Exception:
                    ActionChains(driver).move_to_element(btn).click().perform()
                time.sleep(0.6)
                return
            except TimeoutException:
                continue
            except Exception:
                continue
        try:
            driver.execute_script("""
                const ids = ['onetrust-banner-sdk','onetrust-consent-sdk'];
                ids.forEach(id => { const el = document.getElementById(id); if (el) el.remove(); });
                const modal = document.querySelector('[class*="cookie"], [id*="cookie"]');
                if (modal) modal.remove();
            """)
            time.sleep(0.2)
        except Exception:
            pass

    @staticmethod
    def _wait_for_list(driver, timeout: int = 20):
        end = time.time() + timeout
        while time.time() < end:
            cards = driver.find_elements(By.CSS_SELECTOR, "div.js_cardLink[data-href$='.aspx']")
            if len(cards) >= 3:
                return
            anchors = driver.find_elements(By.CSS_SELECTOR, "a[href*='/vaga-de-'][href$='.aspx']")
            if len(anchors) >= 3:
                return
            driver.execute_script("window.scrollBy(0, 800);")
            time.sleep(0.8)
        raise TimeoutException("Lista de vagas não apareceu a tempo.")

    @staticmethod
    def _parse_list_cards(driver, max_items: Optional[int] = None) -> List[Dict[str, str]]:
        html = driver.page_source
        soup = BeautifulSoup(html, "html.parser")
        seen, results = set(), []

        for card in soup.select("div.js_cardLink[data-href$='.aspx']"):
            href = card.get("data-href")
            if not href:
                continue
            if href.startswith("/"):
                href = "https://www.infojobs.com.br" + href
            h2 = card.select_one("h2")
            title = h2.get_text(strip=True) if h2 else ""
            if len(title) < 5:
                a = card.find("a", href=True)
                if a:
                    title = a.get_text(strip=True)
            if len(title) < 5:
                continue
            key = (title, href)
            if key in seen:
                continue
            seen.add(key)
            results.append({"titulo": title, "url": href})
            if max_items and len(results) >= max_items:
                break

        if (not max_items or len(results) < max_items):
            for a in soup.select("a[href*='/vaga-de-'][href$='.aspx']"):
                href = a.get("href") or ""
                if href.startswith("/"):
                    href = "https://www.infojobs.com.br" + href
                title = a.get_text(strip=True) or ""
                if len(title) < 5:
                    continue
                key = (title, href)
                if key in seen:
                    continue
                seen.add(key)
                results.append({"titulo": title, "url": href})
                if max_items and len(results) >= max_items:
                    break

        if not results:
            with open("debug_infojobs_page.html", "w", encoding="utf-8") as f:
                f.write(html)
            print("💾 Salvei o HTML em debug_infojobs_page.html (abra no navegador).")
        return results

    def _collect_links_infinite_scroll(self, target_links: int = 40, max_loops: int = 60, sleep_between: float = 0.8) -> List[Dict[str, str]]:
        """
        Faz scroll incremental e coleta links até atingir target_links
        ou até ficar N loops sem aumentar a quantidade.
        """
        total: List[Dict[str, str]] = []
        seen = set()
        last_count = 0
        stagnant_loops = 0

        # uma primeira passada de parse (sem scroll)
        items = self._parse_list_cards(self.driver, max_items=None)
        for it in items:
            if it["url"] in seen:
                continue
            seen.add(it["url"])
            total.append(it)

        for loop in range(max_loops):
            if len(total) >= target_links:
                break

            # scroll para baixo + pequena pausa pro site renderizar mais cards
            self.driver.execute_script("window.scrollBy(0, document.body.scrollHeight);")
            time.sleep(sleep_between)

            # parse de novo
            items = self._parse_list_cards(self.driver, max_items=None)
            added_now = 0
            for it in items:
                if it["url"] in seen:
                    continue
                seen.add(it["url"])
                total.append(it)
                added_now += 1
                if len(total) >= target_links:
                    break

            # critério de parada se não estiver crescendo
            if len(total) == last_count:
                stagnant_loops += 1
            else:
                stagnant_loops = 0
                last_count = len(total)

            # se parou de crescer por vários loops, sai (evita laço infinito)
            if stagnant_loops >= 6:
                break

        return total[:target_links]


    @staticmethod
    def _wait_job_detail(driver, timeout: int = 20):
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "#VacancyHeader .js_vacancyHeaderTitle"))
        )
        time.sleep(0.4)

    @staticmethod
    def _extract_detail_fields(html: str) -> Dict[str, Optional[str]]:
        soup = BeautifulSoup(html, "html.parser")

        title = _text(soup.select_one("#VacancyHeader .js_vacancyHeaderTitle"))

        # ---------- EMPRESA (pega o texto completo do <a>, não só o span) ----------
        empresa = None
        h4 = soup.select_one("#VacancyHeader .d-flex.mb-4.align-items-baseline .h4")
        if h4:
            a = h4.find("a", attrs={"target": "_blank"}) or h4  # se não tiver <a>, usa o próprio h4
            # remove ícones/svgs e elementos não textuais que poluem o texto
            for svg in a.find_all("svg"):
                svg.decompose()
            # junta todos os nós de texto preservando espaços (pega “EQUACIONAL ELÉTRICA E” + “MECÂNICA”)
            raw = " ".join(list(a.stripped_strings))
            # limpeza extra
            raw = re.sub(r"\bTrabalhe Conosco\b", "", raw, flags=re.I)
            raw = re.sub(r"\s{2,}", " ", raw).strip()
            # às vezes sobram notas/contagens misturadas; se aparecerem no futuro, adicione regras aqui
            empresa = raw or None

        # fallback para CONFIDENCIAL
        if not empresa and re.search(r"\bCONFIDENCIAL\b", soup.get_text(" ", strip=True), re.I):
            empresa = "CONFIDENCIAL"

        info_blocks = soup.select("#VacancyHeader .text-medium.mb-4")
        localizacao = _text(info_blocks[0]) if len(info_blocks) >= 1 else None
        salario = _text(info_blocks[1]) if len(info_blocks) >= 2 else None
        if salario:
            m = re.search(r"R\$\s?[\d\.\,]+(?:\s*a\s*R\$\s?[\d\.\,]+)?", salario)
            salario = m.group(0) if m else ("A combinar" if re.search(r"\ba combinar\b", salario, re.I) else None)

        modalidade = _text(soup.select_one("#VacancyHeader .text-medium.small.font-weight-bold.mb-4"))
        if modalidade:
            ml = modalidade.lower()
            if any(x in ml for x in ["remoto", "home office", "home-office", "trabalho remoto", "100% remoto"]):
                modalidade = "Remoto"
            elif any(x in ml for x in ["híbrido", "hibrido", "presencial e remoto"]):
                modalidade = "Híbrido"
            elif "presencial" in ml or "in loco" in ml:
                modalidade = "Presencial"
            else:
                modalidade = None

        data_publicacao_raw = _text(soup.select_one("#VacancyHeader .caption.text-medium.text-nowrap.text-right"))
        data_publicacao = _normalize_pub_date(data_publicacao_raw)

        desc_block = soup.select_one("p.mb-16.text-break.white-space-pre-line")
        if desc_block:
            descricao = desc_block.get_text("\n", strip=True)
        else:
            best = ""
            for c in soup.select("div, section, article, p"):
                txt = c.get_text(" ", strip=True)
                if txt and len(txt) > len(best):
                    best = txt
            descricao = best or None

        # ---------- BENEFÍCIOS/REQUISITOS DENTRO DA DESCRIÇÃO ----------
        def _grab_labeled_block(text: str, label_patterns: list[str], stop_patterns: list[str]) -> Optional[str]:
            """
            Após um rótulo (ex.: 'Benefícios:'), captura até o próximo rótulo/stop ou fim.
            Mantém \n no meio para pós-processar.
            """
            if not text:
                return None
            label_regex = r"|".join(label_patterns)
            stop_regex  = r"|".join(stop_patterns) if stop_patterns else r"$"
            m = re.search(rf"({label_regex})\s*(.*?)(?=\r?\n(?:{stop_regex})|\Z)", text, flags=re.I | re.S)

            if not m:
                return None
            block = m.group(2).strip()
            return block if block else None
        
        def _normalize_listish(s: str) -> Optional[str]:
            """
            Normaliza listas: '+' e quebras -> vírgula; no fim vírgulas viram '; '.
            Ex.: 'VT + VR\nAssistência' -> 'VT; VR; Assistência'
            """
            if not s:
                return None
            s = re.sub(r"\s*\+\s*", ", ", s)   # '+' -> ', '
            s = re.sub(r"[\r\n]+", ", ", s)    # quebras -> ', '
            s = re.sub(r"\s*,\s*", ", ", s)    # normaliza vírgulas
            s = s.replace(", ", "; ")
            s = re.sub(r"(;\s*){2,}", "; ", s)
            return s.strip(" ;.,") or None
        
        # ---------- Padrões de captura na descrição ----------
        BEN_LABELS = [
            r"\bbenef[ií]cios?\b[:;]?",
            r"\bvantagens?\b[:;]?",
            r"\bpacote de benef[ií]cios?\b[:;]?",
            r"\bnossos benef[ií]cios\b[:;]?",
            r"\bo que oferecemos\b[:;]?",
            r"\boferecemos\b[:;]?",
            r"\bo que temos para oferecer\b[:;]?",
            r"\bo que voc[eê] vai receber\b[:;]?",
            r"\bo que voc[eê] ter[áa] direito\b[:;]?",
            r"\bo que proporcionamos\b[:;]?",
            r"\btemos para voc[eê]\b[:;]?",
            r"\baqui voc[eê] encontra\b[:;]?",
            r"\bo que disponibilizamos\b[:;]?",
            r"\bo que garantimos\b[:;]?",
            r"\bo que a empresa oferece\b[:;]?",
            r"\bbenef[ií]cios inclusos\b[:;]?",
            r"\bperks?\b[:;]?",
            r"\bregalias?\b[:;]?",
            r"\bnossos diferenciais\b[:;]?",
            r"\batrativos?\b[:;]?",
            r"\bnossos atrativos\b[:;]?",
            r"\bofertas para voc[eê]\b[:;]?",
            r"\bo que voc[eê] ganha\b[:;]?",
        ]

        REQ_LABELS = [
            # clássicos
            r"\brequisitos?\b[:;]?",
            r"\brequisitos necess[aá]rios?\b[:;]?",
            r"\bpr[eé]-?requisitos?\b[:;]?",
            r"\brequisitos obrigat[oó]rios?\b[:;]?",
            r"\brequisitos e qualifica[cç][oõ]es?\b[:;]?",
            r"\bqualifica[cç][oõ]es?\b[:;]?",
            r"\bhabilidades necess[aá]rias?\b[:;]?",
            r"\bexperi[eê]ncia necess[aá]ria?\b[:;]?",
            r"\bexperi[eê]ncia m[ií]nima\b[:;]?",
            r"\bexperi[eê]ncia desejada\b[:;]?",
            r"\bperfil desejado\b[:;]?",
            r"\bexig[eê]ncias?\b[:;]?",
            r"\bexigimos\b[:;]?",
            r"\bnecess[aá]rio\b[:;]?",
            r"\bnecess[aá]rio conhecimento em\b[:;]?",
            r"\bconhecimentos necess[aá]rios?\b[:;]?",
            r"\bconhecimentos t[eé]cnicos?\b[:;]?",
            r"\bstack necess[aá]ria\b[:;]?",
            # conversacionais
            r"\bo que esperamos\b[:;]?",
            r"\bvoc[eê] precisa ter\b[:;]?",
            r"\bo que buscamos\b[:;]?",
            r"\bo que voc[eê] precisa\b[:;]?",
            r"\bseu papel ser[aá]\b[:;]?",
            r"\bquem [eé] voc[eê]\b[:;]?",
            r"\bo candidato deve\b[:;]?",
            # formação
            r"\bforma[cç][aã]o\b[:;]?",
            r"\bform[aã]o acad[eê]mica\b[:;]?",
            r"\bcursos?\b[:;]?",
            r"\bhard skills?\b[:;]?",
            r"\bsoft skills?\b[:;]?",
        ]

        STOP_LABELS = [
            r"\batividades?\b[:;]?",
            r"\bresponsabilid",             # pega 'responsabilidades'
            r"\brequisitos?\b[:;]?",        # parar no próximo bloco de requisitos
            r"\bqualifica",                 # pega 'qualificações'
            r"\bbenef[ií]cios?\b[:;]?",
            r"\bpr[eé]-?requisitos?\b[:;]?",
            r"\brequisitos obrigat[oó]rios?\b[:;]?",
            r"\bn[uú]mero de vagas\b[:;]?",
            r"\btipo de contrato\b[:;]?",
            r"\bvalorizado\b[:;]?",
            r"\bhor[áa]rio\b[:;]?",
            r"\blocal\b[:;]?",
            r"\bescala\b[:;]?",
            r"\bjornada\b[:;]?",
            r"\bsal[áa]rio\b[:;]?",
            # paradas extras solicitadas
            r"\bmodelo de trabalho\b[:;]?",
            r"\blocal de trabalho e formato\b[:;]?",
        ]       

        
        def _extract_from_description(text: Optional[str]) -> tuple[Optional[str], Optional[str]]:
            """Retorna (beneficios_desc_norm, requisitos_desc_norm) já limpos (sem cifras etc.)."""
            if not text:
                return (None, None)
            ben = _grab_labeled_block(text, BEN_LABELS, STOP_LABELS)
            ben = _normalize_listish(ben) if ben else None
            ben = _clean_beneficios(ben) if ben else None

            req = _grab_labeled_block(text, REQ_LABELS, STOP_LABELS)
            if req:
                looks_list = bool(re.search(r"[\n\*•;-]", req))
                req = _normalize_listish(req) if looks_list else req.strip()
            req = _clean_requisitos(req) if req else None
            return (ben, req)


        # ---------- TIPO DE CONTRATO ----------
        tipo_contrato = None
        for p in soup.select(".pt-24.text-medium.js_vacancyDataPanels p"):
            t = _text(p) or ""
            if "Tipo de contrato" in t or "Regime" in t:
                for l in ["CLT", "PJ", "Estágio", "Temporário", "Meio período", "Jovem Aprendiz", "Outros", "Autônomo", "Cooperado", "Trainee", "Freelancer", "Intermitentes"]:
                    if re.search(rf"\b{re.escape(l)}\b", t, re.I):
                        tipo_contrato = l
                        break
            if tipo_contrato: break


        requisitos = extract_section_list(soup, r"Exigências")
        beneficios = extract_section_list(soup, r"Benefícios|Vale|Assistência|Plano|Seguro")

        # ---- TRATAMENTO ESPECÍFICO ----        
        def _split_tokens(s: str) -> list[str]:
            if not s:
                return []
            # trata bullets do tipo " - " como separador
            s = re.sub(r"\s+-\s+", "\n", s)
            # separa por ; , \n | / • * e dois-pontos — NÃO separa por hífen simples
            parts = re.split(r"[;\,\n\|/•\*:]+", s)
            return [p.strip() for p in parts if p and p.strip()]

        def _dedupe_keep_order(items: list[str]) -> list[str]:
            seen = set()
            out = []
            for it in items:
                key = it.lower()
                if key not in seen:
                    seen.add(key)
                    out.append(it)
            return out

        def _to_list(s: Optional[str]) -> list[str]:
            if not s or s == "NULL":
                return []
            parts = re.split(r"[;\,\n\|/•\*:]+", s)
            return [p.strip() for p in parts if p.strip()]

        def _join_list(items: list[str]) -> Optional[str]:
            items = [i.strip() for i in items if i and i.strip()]
            return "; ".join(items) if items else None
        
        # palavras/raizes que caracterizam BENEFÍCIOS
        _BEN_PAT = re.compile(
            r"\b("
            r"vale(-|\s)?(transporte|refei[cç][aã]o|aliment[aã]o|combust[ií]vel)|"
            r"vr|va|vt|vg|aux[ií]lio|auxilio|plano|assist[eê]ncia|conv[eê]nio|"
            r"odontol[oó]gica|m[eé]dica|sa[uú]de|seguro|vida|plr|"
            r"previd[eê]ncia|gym|wellhub|estacionamento|day\s*off|"
            r"home\s*office|teletrabalho|cart[aã]o|refei[cç][aã]o|aliment[aã]o|"  # ← PIPE ADICIONADO
            r"psicol[oó]gico|jur[íi]dico|financeiro"  # ← NOVOS PADRÕES
            r")\b",
            re.I
        )

        _MONEY_PATTS = [
            re.compile(r"R\$\s*[\d\.\,]+", re.I),
            re.compile(r"\b\d{1,3}(?:\.\d{3})*(?:,\d{2})\b"),
            re.compile(r"\b\d+,\d{2}\b"),
            re.compile(r"\((?:[^()]*(?:R\$|\d)[^()]*)\)"),  # remove o bloco inteiro entre parênteses se tiver número/R$
            re.compile(r"\b\d{1,3}\b"),  # por fim, números pequenos soltos (ex.: "00", "23")
        ]

        def _strip_money(text: str) -> str:
            if not text:
                return text
            for pat in _MONEY_PATTS:
                text = pat.sub("", text)
            # limpa conectores que ficaram antes/depois dos valores
            text = re.sub(r"\s*-\s*(?:;|,)?", " ", text)
            text = re.sub(r"\s{2,}", " ", text)
            return text.strip(" ,;.-")
        
        def _clean_beneficios(text: Optional[str]) -> Optional[str]:
            if not text:
                return None
            text = _strip_money(text)
            tokens = _split_tokens(text)

            # mantém só itens que parecem benefícios
            tokens = [t for t in tokens if _BEN_PAT.search(t)]

            # normaliza e remove resíduos
            cleaned = []
            for t in tokens:
                t = _strip_money(t)
                t = re.sub(r"\s{2,}", " ", t).strip(" ,;.-")
                # pequenas normalizações
                t = t.replace("vale refeicao", "Vale refeição").replace("vale alimentacao", "Vale alimentação")
                cleaned.append(t)

            cleaned = [t for t in cleaned if t]
            cleaned = _dedupe_keep_order(cleaned)

            return "; ".join(cleaned) if cleaned else None

            
        def _clean_requisitos(text: Optional[str]) -> Optional[str]:
            if not text:
                return None

            # --- padrões de coisas que NÃO são requisitos (deny) ---
            BENEF_PAT = re.compile(
                r"\b(benef[ií]cios?|vale(-|\s)?(transporte|refei[cç][aã]o|aliment[aã]o|combust[ií]vel)|"
                r"vr|va|vt|vg|assist[eê]ncia|plano|conv[eê]nio|odontol[oó]gica|m[eé]dica|sa[uú]de|"
                r"seguro|vida|plr|previd[eê]ncia|gym|wellhub|estacionamento|day\s*off|"
                r"cart[aã]o|premia[cç][aã]o|b[oô]nus|ppr|aux[ií]lio|auxilio|"
                r"remunera[cç][aã]o|sal[aá]rio|pacote|vale|fretado|total\s*pass)\b",
                re.I
            )

            CULT_PAT = re.compile(
                r"\b(cultura|ambiente|diversidade|inclus[aã]o|prop[oó]sito|o que oferecemos|"
                r"o que buscamos|por que trabalhar|nossa empresa|nosso time|inform[aá]coes adicionais?)\b",
                re.I
            )

            ADMIN_PAT = re.compile(
                r"\b(local\s*de\s*trabalho|modelo\s*de\s*trabalho|h[oô]r[áa]rio|escala|"
                r"formato\s*h[ií]brido|presencial|remoto|zona\s*sul|berrini|copacabana|pinheiros|"
                r"disponibilidade|residir|documenta[cç][aã]o|como te apoiaremos|como [é] o time|"
                r"atribu[ií]c[oõ]es|responsabilid|principais atividades?)\b",
                re.I
            )

            MONEY_PAT = re.compile(r"(R\$\s*[\d\.\,]+|\b\d{1,3}(?:\.\d{3})*(?:,\d{2})\b|\b\d+%|\b\d+\s*dias?)", re.I)

            # --- padrões de itens que PARECEM requisitos (allow) ---
            SKILL_PAT = re.compile(
                r"\b(sql|python|r\b|excel|power\s*bi|tableau|looker|spark|hadoop|airflow|kafka|"
                r"oracle|postgres|mysql|sql\s*server|pl\/?sql|no\s*sql|docker|kubernetes|git|linux|"
                r"aws|azure|gcp|databricks|pandas|numpy|matplotlib|etl|el[t]?|modelagem\s*de\s*dados?)\b",
                re.I
            )
            FORMACAO_PAT = re.compile(
                r"\b(ensino\s*m[eé]dio|t[eé]cnico|gradua[cç][aã]o|superior|ci[eê]ncia\s*da\s*computa[cç][aã]o|"
                r"sistemas\s*de\s*informa[cç][aã]o|engenharia\s*de\s*software|estat[ií]stica|m[aá]tem[aá]tica)\b",
                re.I
            )
            EXP_PAT = re.compile(r"\bexperi[eê]ncia|viv[eê]ncia|dom[ií]nio|conhecimento(s)?\b", re.I)

            def _split_tokens(s: str) -> list[str]:
                s = re.sub(r"\s+-\s+", "\n", s)           # " - " como separador de bullet
                parts = re.split(r"[;\,\n\|/•\*:]+", s)   # separa em itens
                return [p.strip() for p in parts if p and p.strip()]

            def _dedupe_keep_order(items: list[str]) -> list[str]:
                seen, out = set(), []
                for it in items:
                    k = it.lower()
                    if k not in seen:
                        seen.add(k)
                        out.append(it)
                return out

            # 1) remove números/cifras, limpa espaços
            text = re.sub(MONEY_PAT, "", text)
            text = re.sub(r"\s{2,}", " ", text).strip(" ,;.-:")

            # 2) tokeniza
            tokens = _split_tokens(text)

            # 3) filtra: remove benefícios, cultura/marketing, administrativos e itens vazios
            def _is_noise(tok: str) -> bool:
                t = tok.lower()
                return (
                    len(t) < 3 or
                    BENEF_PAT.search(t) or
                    CULT_PAT.search(t) or
                    ADMIN_PAT.search(t) or
                    MONEY_PAT.search(t) or
                    re.search(r"^informa[cç][oõ]es? adicionais?[:\-]?$", t, re.I) or
                    re.search(r"^o que oferecemos[:\-]?$", t, re.I) or
                    re.search(r"^principais (atividades|responsabilidades)[:\-]?$", t, re.I)
                )

            tokens = [t for t in tokens if not _is_noise(t)]

            # 4) mantém só o que parece requisito (skills/formaçao/experiência)
            def _looks_like_requirement(tok: str) -> bool:
                t = tok.lower()
                return SKILL_PAT.search(t) or FORMACAO_PAT.search(t) or EXP_PAT.search(t)

            tokens = [t for t in tokens if _looks_like_requirement(t)]

            # 5) limpeza final + dedupe
            tokens = [re.sub(r"\s{2,}", " ", t).strip(" ,;.-:") for t in tokens]
            tokens = [t for t in tokens if t]
            tokens = _dedupe_keep_order(tokens)

            return "; ".join(tokens) if tokens else None



        requisitos = _clean_requisitos(requisitos)
        beneficios = _clean_beneficios(beneficios)

    

        # ----- localizacao 
        if localizacao:
            m = re.search(r"([A-Za-zÀ-ú\.\'\-\s]+)\s-\s([A-Z]{2})", localizacao)
            localizacao = f"{m.group(1).strip()} - {m.group(2).strip()}" if m else localizacao



        # ---------- LLM como FONTE PRINCIPAL de requisitos/benefícios / PRIORIDADE usar LLM SOMENTE SE FUNCIONAR; senão, fallback ----------
        desc_text = descricao or ""
        llm_ok = False
        llm_reqs_list: list[str] = []
        llm_bens_list: list[str] = []

        if DEBUG_LLM:
            print(f"[LLM] USE_LLM={USE_LLM}, LLM_ONLY={LLM_ONLY_MODE}, tam(desc)={len(desc_text)}")
            
        # 1) TENTA LLM (se ativado)
        if USE_LLM and GROQ_API_KEY and len(desc_text) > 60:
            try:
                print("[LLM] Tentando extrair com Groq...")
                llm_result = llm_extract_req_benef(desc_text)
                llm_reqs_list = [x.strip() for x in llm_result.get("requisitos", []) if isinstance(x, str) and x.strip()]
                llm_bens_list = [x.strip() for x in llm_result.get("beneficios", []) if isinstance(x, str) and x.strip()]
                llm_ok = bool(llm_reqs_list or llm_bens_list)

                if not llm_ok and LLM_ONLY_MODE:
                    raise RuntimeError("LLM_ONLY_FAILED")
        
                if llm_ok:
                    print(f"[LLM] SUCESSO → req: {len(llm_reqs_list)}, ben: {len(llm_bens_list)}")

            except RuntimeError:
                raise  # Re-lança RuntimeError sem modificar
            except Exception as e:
                print(f"[LLM] FALHOU → {str(e)[:100]}")
                if LLM_ONLY_MODE:
                    raise RuntimeError("LLM_ONLY_FAILED") from e
                llm_ok = False

            else:
                # Se chegou aqui sem erro → LLM OK
                pass
        else:
            if LLM_ONLY_MODE:
                print("[LLM-ONLY] LLM não foi tentada (chave ausente ou descrição curta).")
                raise RuntimeError("LLM_ONLY_FAILED")
            llm_ok = False

        # 2) SE LLM OK → usa ele
        if llm_ok:
            base_reqs = _to_list(requisitos) if requisitos else []
            requisitos = _join_list(_dedupe_keep_order(base_reqs + llm_reqs_list)) or "NULL"
            beneficios = _join_list(_dedupe_keep_order(llm_bens_list)) or "NULL"
            print("[LLM] Usando LLM como fonte principal.")

        # 3) SE LLM FALHOU E NÃO É LLM_ONLY → fallback
        elif not LLM_ONLY_MODE:
            print("[LLM] FALLBACK → usando rótulos da descrição.")
            ben_desc, req_desc = _extract_from_description(desc_text)
            base_reqs = _to_list(requisitos) if requisitos else []
            desc_reqs = _to_list(req_desc) if req_desc else []
            requisitos = _join_list(_dedupe_keep_order(base_reqs + desc_reqs)) or "NULL"
            beneficios = ben_desc or "NULL"

        # Padronização extra de 'requisitos'
        if requisitos and requisitos != "NULL":
            s = requisitos

            # remove rótulos soltos (Obrigatório, Desejável, Diferenciais, etc.)
            s = re.sub(r"(?i)(^|;\s*)(obrigat[óo]rio|desej[aá]vel|diferenciais?|requisitos?|pr[eé]-?requisitos?)\b:?\s*(;|$)", r"\1", s)

            # --- Normalizações específicas de "Escolaridade Mínima" ---
            # "Escolaridade: Mínima: Ensino Médio"  -> "Escolaridade Mínima: Ensino Médio"
            s = re.sub(r"(?i)\bEscolaridade\s*:\s*M[ií]nima\s*:\s*([^;]+)", r"Escolaridade Mínima: \1", s)
            # "Escolaridade : Mínima  Ensino Médio" -> "Escolaridade Mínima: Ensino Médio"
            s = re.sub(r"(?i)\bEscolaridade\s*:\s*M[ií]nima\s+(?!:)([^;]+)", r"Escolaridade Mínima: \1", s)
            # "Escolaridade Mínima; Curso Técnico"  -> "Escolaridade Mínima: Curso Técnico"
            s = re.sub(r"(?i)\bEscolaridade\s*M[ií]nima\b\s*;\s*([^;]+)", r"Escolaridade Mínima: \1", s)
            # "Escolaridade Mínima Curso Técnico"   -> "Escolaridade Mínima: Curso Técnico"
            s = re.sub(r"(?i)\bEscolaridade\s*M[ií]nima\b\s+(?!:)([^;]+)", r"Escolaridade Mínima: \1", s)

            # --- Corrige "Formação" ou "Escolaridade" simples,
            #     mas NÃO quando a próxima palavra for 'Mínima' ---
            s = re.sub(r"(?i)\bEscolaridade\b\s*;\s*(?!M[ií]nima\b)([^;:]+)", r"Escolaridade: \1", s)
            s = re.sub(r"(?i)\bEscolaridade\b\s+(?!M[ií]nima\b)([^;:]+)",          r"Escolaridade: \1", s)
            s = re.sub(r"(?i)\bForma[cç][aã]o\b\s*;\s*([^;:]+)",                   r"Formação: \1",     s)
            s = re.sub(r"(?i)\bForma[cç][aã]o\b\s+(?!:)([^;:]+)",                  r"Formação: \1",     s)

            # Limpezas finais
            s = re.sub(r"(;\s*){2,}", "; ", s)   # colapsa ;;;
            s = re.sub(r":\s*:\s*", ": ", s)     # evita ": :"
            requisitos = s.strip(" ;") or requisitos

        # conversão final: None → "NULL"
        def _null_if_none(v):
            return v if (v and v.strip()) else "NULL"

        title = _null_if_none(title)
        empresa = _null_if_none(empresa)
        localizacao = _null_if_none(localizacao)
        salario = _null_if_none(salario)
        descricao = _null_if_none(descricao)
        requisitos = _null_if_none(requisitos)
        beneficios = _null_if_none(beneficios)
        tipo_contrato = _null_if_none(tipo_contrato)
        modalidade = _null_if_none(modalidade)
        data_publicacao = _null_if_none(data_publicacao)  

        return {
            "titulo_vaga": title,
            "empresa": empresa,
            "localizacao": localizacao,
            "salario": salario,
            "descricao": descricao,
            "requisitos": requisitos,
            "beneficios": beneficios,
            "tipo_contrato": tipo_contrato,
            "modalidade": modalidade,
            "data_publicacao": data_publicacao,
        }

    # ---- API pública
    def search_list(self) -> List[Dict[str, str]]:
        url = self._build_list_url(self.term, self.city_slug, page=1)
        print(f"\n[ABRINDO] {url}")
        self._safe_get(url)
        
        self._wait_and_accept_cookies(self.driver, timeout=15)

        self.driver.execute_script("window.scrollTo(0, 600);")
        time.sleep(1.0)
        self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1.0)

        try:
            self._wait_for_list(self.driver, timeout=18)
        except Exception:
            print("⚠️  Não encontrei a lista ainda. Vou tentar mesmo assim…")

        items = self._collect_links_infinite_scroll(target_links=self.target_links, max_loops=60, sleep_between=0.9)

        print(f"→ Itens encontrados nesta página: {len(items)}")
        for i, it in enumerate(items, 1):
            print(f"{i:02d}. {it['titulo']}\n    {it['url']}")
        print(f"\n✅ Total coletado no passo 1: {len(items)} links")
        return items

    def parse_detail(self, url: str) -> Dict[str, Optional[str]]:
        self._safe_get(url)
        self._wait_job_detail(self.driver)
        html = self.driver.page_source
        data = self._extract_detail_fields(html)

        # retry rápido se veio descrição muito curta ou título NULL
        if (not data.get("descricao") or data.get("descricao") == "NULL") or (data.get("titulo_vaga") in (None, "NULL")):
            time.sleep(0.7)
            self._safe_get(url)
            self._wait_job_detail(self.driver)
            html = self.driver.page_source
            data = self._extract_detail_fields(html)

        # padronização final
        data["url_vaga"] = url
        data["fonte"] = "Infojobs.com.br"
        if ZoneInfo:
            data["data_coleta"] = datetime.now(ZoneInfo("America/Sao_Paulo")).isoformat()
        else:
            data["data_coleta"] = datetime.now().isoformat()
        return data

    def close(self):
        try:
            self.driver.quit()
        except Exception:
            pass


# -------------------------- CLI --------------------------
def main():
    parser = argparse.ArgumentParser(description="InfoJobs Scraper (Selenium)")
    parser.add_argument("--term", default="programador", help="termo (ex: programador, desenvolvedor python)")
    parser.add_argument("--city", default=None, help="slug da cidade (ex: sao-paulo,-sp)")
    parser.add_argument("--headless", action="store_true", help="rodar sem abrir janela")
    parser.add_argument("--max-jobs", type=int, default=3, help="quantos detalhes abrir (para teste)")
    parser.add_argument("--keywords", nargs="*", default=PYTHON_KEYWORDS, help="filtrar por palavras-chave (título+descrição)")
    parser.add_argument("--use-llm", action="store_true", help="usar LLM (Groq) para extrair requisitos/benefícios")
    parser.add_argument("--use-llm-only", action="store_true", help="usar SÓ LLM → para se falhar")
    parser.add_argument("--dry-run", action="store_true",help="não conecta no banco nem insere; só coleta e imprime")
    parser.add_argument("--terms", nargs="+", help="lista de termos de busca (substitui --term)")
    parser.add_argument("--use-default-keywords", action="store_true", help="se nenhum --term/--terms for passado, usa a lista PYTHON_KEYWORDS inteira")
    parser.add_argument("--flush-every", type=int, default=10, help="salva a cada N vagas coletadas")
    parser.add_argument("--target-links", type=int, default=12, help="quantos links coletar por keyword (default: 12)")
    args = parser.parse_args() 

    if args.max_jobs is None or args.max_jobs <= 0:
        args.max_jobs = args.target_links

    FLUSH_EVERY = max(1, args.flush_every)   # salva a cada 10 vagas coletadas

    # ---------------- Termos de busca ----------------
    if args.terms:
        search_terms = args.terms
    elif args.term and not args.use_default_keywords:
        search_terms = [args.term]
    else:
        # usa a lista inteira PYTHON_KEYWORDS se --use-default-keywords foi passado
        # ou se nenhum --term/--terms foi fornecido
        search_terms = PYTHON_KEYWORDS

    # Conecta ao banco (só se não for dry-run)
    conn = None
    if not args.dry_run:
        conn = conectar_banco()
        if not conn:
            print("❌ Não foi possível conectar ao banco. Encerrando.")
            return
        print(f"\n📊 ESTADO INICIAL DO BANCO:")
        verificar_vagas_salvas(conn)
    else:
        print("🧪 Modo dry-run: conexão com banco desativada.")

    global USE_LLM, LLM_ONLY_MODE
    USE_LLM = args.use_llm or args.use_llm_only  # ativa se qualquer um
    LLM_ONLY_MODE = args.use_llm_only           # só para se falhar

     # ------------------ LOOP PRINCIPAL DE BUSCA ------------------

    seen_urls = set()        # evita duplicar a mesma vaga entre termos
   

    buffer = []
    total_salvas = 0
    llm_critical_stop = False

    for term in search_terms:
        if llm_critical_stop: 
            break
        print(f"\n==============================")
        print(f"🔎 Buscando termo: {term}")
        print(f"==============================")

        sj = InfoJobsScraper(term=term, city_slug=args.city, headless=args.headless, target_links=args.target_links)

        try:
            lst = sj.search_list()
            links = [it["url"] for it in lst if it["url"] not in seen_urls]
            for u in links:
                seen_urls.add(u)

            print("Obs.: Próximo passo: abrir cada URL e extrair os detalhes.")

            picked = 0
            skipped_keywords = 0
            errors = 0

            for idx, url in enumerate(links, 1):
                print(f"[{idx}/{len(links)}] detalhando: {url}")
                time.sleep(0.6)

                try:
                    data = sj.parse_detail(url)

                # ── Captura erro ESPECÍFICO do LLM ──
                except RuntimeError as e:
                    if "LLM_ONLY_FAILED" in str(e):
                        print(f"\n❌ [LLM-ONLY] Falha crítica: {e}")
                        print(f"   URL: {url}")
                        llm_critical_stop = True  # ← Ativa a flag
                        break  # ← Sai do loop de vagas
                    else:
                        # RuntimeError que não é do LLM → trata como erro normal
                        errors += 1
                        print(f"Erro RuntimeError: {e}")
                        continue

                # ── Captura OUTROS erros (timeout, elemento não encontrado, etc) ──
                except Exception as e:
                    errors += 1
                    print(f"Erro ao processar vaga: {url} -> {e}")
                    continue  # ← Continua processando outras vagas

                titulo = (data.get("titulo_vaga") or "")
                desc = (data.get("descricao") or "")

                # filtro por keywords (usa args.keywords - por padrão PYTHON_KEYWORDS)
                if not contains_keywords(titulo + " " + desc, args.keywords):
                    skipped_keywords += 1
                    continue

                # imprime o “registro padronizado” (ótimo para dry-run)
                def _sanitize(v):
                    if v is None:
                        return "NULL"
                    v = re.sub(r"[\r\n\t]+", " ", str(v))
                    v = re.sub(r"\s{2,}", " ", v).strip()
                    return v or "NULL"

                bloco = [
                    "— Registro padronizado:",
                    f"  titulo_vaga: {_sanitize(data.get('titulo_vaga'))}",
                    f"  empresa: {_sanitize(data.get('empresa'))}",
                    f"  localizacao: {_sanitize(data.get('localizacao'))}",
                    f"  salario: {_sanitize(data.get('salario'))}",
                    f"  tipo_contrato: {_sanitize(data.get('tipo_contrato'))}",
                    f"  modalidade: {_sanitize(data.get('modalidade'))}",
                    f"  data_publicacao: {_sanitize(data.get('data_publicacao'))}",
                    f"  url_vaga: {_sanitize(data.get('url_vaga'))}",
                    f"  fonte: {_sanitize(data.get('fonte'))}",
                    f"  data_coleta: {_sanitize(data.get('data_coleta'))}",
                    f"  descricao: {_sanitize((data.get('descricao') or '')[:200] + ('…' if data.get('descricao') and len(data.get('descricao')) > 200 else ''))}",
                    f"  requisitos: {_sanitize(data.get('requisitos'))}",
                    f"  beneficios: {_sanitize(data.get('beneficios'))}",
                    "-" * 80,
                ]
                print("\n".join(bloco), flush=True)

                # acumula para DB
                buffer.append(_prep_row_for_db({
                    "titulo_vaga": data.get("titulo_vaga"),
                    "empresa": data.get("empresa"),
                    "localizacao": data.get("localizacao"),
                    "salario": data.get("salario"),
                    "descricao": data.get("descricao"),
                    "requisitos": data.get("requisitos"),
                    "beneficios": data.get("beneficios"),
                    "tipo_contrato": data.get("tipo_contrato"),
                    "modalidade": data.get("modalidade"),
                    "data_publicacao": data.get("data_publicacao"),
                    "url_vaga": data.get("url_vaga"),
                    "fonte": "Infojobs.com.br",
                }))
                # flush periódico
                if not args.dry_run and len(buffer) >= FLUSH_EVERY:
                    print(f"\n💾 Salvando lote parcial de {len(buffer)} vagas...")
                    conn = salvar_vagas_supabase(conn, buffer, lote_size=50)
                    total_salvas += len(buffer)
                    buffer.clear()

                picked += 1
                if picked >= args.max_jobs:
                    break

            if buffer and not args.dry_run:
                print(f"\n💾 Salvando lote final de {len(buffer)} vagas...")
                conn = salvar_vagas_supabase(conn, buffer, lote_size=50)
                total_salvas += len(buffer)
                buffer.clear()

            print(f"\n✅ Total enviado ao banco nesta execução: {total_salvas} vagas.")
            if args.dry_run:
                print("🧪 Dry-run: nenhuma vaga foi salva (apenas coleta/teste).")


            print(f"\nResumo ({term}): coletados={picked}, erros={errors}, pulados_keywords={skipped_keywords}")

            if llm_critical_stop:  
                break             

        finally:
            sj.close()

        if llm_critical_stop:  
            break              

        # pausa curtinha entre termos pra ser educado com o site
        time.sleep(1.5)

    if llm_critical_stop:
        print("\n🛑 SCRAPER INTERROMPIDO: LLM obrigatório falhou")
        if not args.dry_run:
            print(f"   Vagas salvas antes da falha: {total_salvas}")
        sys.exit(1)
        


if __name__ == "__main__":
    main()
