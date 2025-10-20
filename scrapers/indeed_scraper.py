import undetected_chromedriver as uc
import psycopg2
import time
import re

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchWindowException, WebDriverException
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from datetime import datetime

# 🔴 COLE SUA CONNECTION STRING AQUI
CONNECTION_STRING = "postgresql://postgres.wnhqaiogzvvwrxcgfwsj:abkm@aws-1-sa-east-1.pooler.supabase.com:5432/postgres"

def conectar_banco():
    """Conecta ao banco PostgreSQL do Supabase"""
    try:
        conn = psycopg2.connect(CONNECTION_STRING)
        print("✅ Conectado ao Supabase com sucesso!")
        return conn
    except Exception as e:
        print(f"❌ Erro na conexão: {e}")
        return None

def limpar_texto(texto):
    """Remove caracteres desnecessários e limpa o texto"""
    if not texto:
        return "Não informado"
    
    texto = re.sub(r'\s+', ' ', texto.strip())
    texto = re.sub(r'[^\w\s\-\.,;:()R$%+/]', '', texto)
    
    return texto if texto else "Não informado"

def extrair_requisicoes(detail_soup):
    """
    Extrai requisitos da vaga usando múltiplas estratégias devido à inconsistência do HTML
    """
    requisitos = []
    
    requirement_keywords = [
        'requisitos', 'qualificações', 'requirements', 'qualifications', 
        'conhecimentos', 'skills', 'competências', 'experiência'
    ]
    
    headers = detail_soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'b', 'strong'])
    for header in headers:
        header_text = header.get_text().lower().strip()
        if any(keyword in header_text for keyword in requirement_keywords):
            next_sibling = header.find_next_sibling()
            if next_sibling and next_sibling.name == 'ul':
                items = next_sibling.find_all('li')
                for item in items:
                    req_text = item.get_text(strip=True)
                    if req_text and len(req_text) > 5:
                        requisitos.append(req_text)
            
            elif next_sibling and next_sibling.name == 'p':
                current = next_sibling
                while current and current.name == 'p':
                    p_text = current.get_text(strip=True)
                    if p_text and len(p_text) > 10:
                        requisitos.append(p_text)
                    current = current.find_next_sibling()
            
            parent = header.parent
            if parent:
                lists = parent.find_all('ul')
                for ul in lists:
                    items = ul.find_all('li')
                    for item in items:
                        req_text = item.get_text(strip=True)
                        if req_text and len(req_text) > 5:
                            requisitos.append(req_text)
    
    tech_keywords = [
        'python', 'javascript', 'angular', 'react', 'java', 'sql', 'nosql',
        'api', 'rest', 'git', 'docker', 'kubernetes', 'aws', 'azure',
        'experiência', 'anos', 'superior', 'graduação', 'formação'
    ]
    
    all_lists = detail_soup.find_all('ul')
    for ul in all_lists:
        items = ul.find_all('li')
        list_text = ul.get_text().lower()
        if any(keyword in list_text for keyword in tech_keywords):
            for item in items:
                req_text = item.get_text(strip=True)
                if req_text and len(req_text) > 5 and req_text not in requisitos:
                    requisitos.append(req_text)
    
    paragraphs = detail_soup.find_all('p')
    for p in paragraphs:
        p_text = p.get_text()
        if re.search(r'[·•▪▫-]\s*\d+[–\-]\d+\s*anos?', p_text, re.IGNORECASE) or \
           re.search(r'[·•▪▫-]\s*(experiência|conhecimento)', p_text, re.IGNORECASE):
            
            lines = re.split(r'[·•▪▫]', p_text)
            for line in lines[1:]:
                req_text = line.strip()
                if req_text and len(req_text) > 10 and req_text not in requisitos:
                    requisitos.append(req_text)
    
    cleaned_requisitos = []
    for req in requisitos:
        req = re.sub(r'^[;\-·•▪▫\s]+', '', req)
        req = re.sub(r'[;\-\s]+$', '', req)
        
        if len(req) > 5 and req not in cleaned_requisitos:
            cleaned_requisitos.append(req)
    
    return ' | '.join(cleaned_requisitos) if cleaned_requisitos else "Não informado"

def scrape_indeed(keyword, location, max_pages=1):

    options = uc.ChromeOptions()
    options.add_argument("--window-size=1280,800")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36")
    options.add_argument("--disable-popup-blocking")

    driver = uc.Chrome(options=options)
    results = []
    base_url = "https://br.indeed.com"

    url = f"{base_url}/jobs?q={keyword}&l={location}"
    driver.get(url)
    print("-> Please complete the captcha/verification in the browser that appears ")
    input("-> Press Enter if the verification is complete") 

    for page in range(max_pages):
        start = page * 10
        page_url = f"{base_url}/jobs?q={keyword}&l={location}&start={start}"
        print(f"Scrape Page {page+1}: {page_url}")
        driver.get(page_url)

        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div.job_seen_beacon"))
            )
        except Exception as e:
            print(f"Can't find job listing on page {page+1}. Error: {e}")
            break

        soup = BeautifulSoup(driver.page_source, "html.parser")
        
        job_cards = soup.select("div.job_seen_beacon")

        for job in job_cards:
            title_tag = job.select_one('a.jcs-JobTitle')
            company_tag = job.select_one('span[data-testid="company-name"]')
            location_tag = job.select_one('div[data-testid="text-location"]')
            
            job_title = limpar_texto(title_tag.get_text()) if title_tag else "Não informado"
            company_name = limpar_texto(company_tag.get_text()) if company_tag else "Não informado"
            job_salario = "Não informado"
            job_tipo = "Não informado"

            job_modalidade = "Não informado"
            job_location = "Não informado"
            job_beneficios = "Não informado"
            job_requisitos = "Não informado"
            job_description = "Não informado" 
            job_url = "Não informado"
            data_publicacao = datetime.now().date()

            if location_tag:
                full_text = location_tag.get_text(strip=True)
                if " in " in full_text.lower():
                    parts = full_text.split(" in ", 1)
                    job_modalidade = limpar_texto(parts[0])
                    job_location = limpar_texto(parts[1])
                else:
                    job_location = limpar_texto(full_text)

            if title_tag and 'href' in title_tag.attrs:
                relative_url = title_tag['href']
                detail_page_url = urljoin(base_url, relative_url)
                
                print(f"    -> Visit the details page for '{job_title}'...")
                original_window = driver.current_window_handle
                
                try:
                    driver.execute_script("window.open('');")
                    WebDriverWait(driver, 10).until(EC.number_of_windows_to_be(2))
                    
                    for window_handle in driver.window_handles:
                        if window_handle != original_window:
                            driver.switch_to.window(window_handle)
                            break
                    
                    driver.get(detail_page_url)
                    
                    time.sleep(1)
                    job_url = driver.current_url
                    
                    try:
                        page_loaded = False
                        selectors_to_try = [
                            (By.ID, "jobDescriptionText"),
                            (By.CSS_SELECTOR, "div.jobsearch-JobComponent"),
                            (By.CSS_SELECTOR, "div.jobsearch-ViewJobLayout"),
                            (By.ID, "jobsearch-ViewjobPaneWrapper"),
                            (By.CSS_SELECTOR, "div[data-testid='jobsearch-JobInfoHeader']")
                        ]
                        
                        for selector_type, selector_value in selectors_to_try:
                            try:
                                WebDriverWait(driver, 5).until(
                                    EC.presence_of_element_located((selector_type, selector_value))
                                )
                                page_loaded = True
                                print(f"        ✓ Página carregada (seletor: {selector_value[:30]}...)")
                                break
                            except TimeoutException:
                                continue
                        
                        if not page_loaded:
                            print(f"        ⚠ Nenhum seletor funcionou, tentando extrair mesmo assim...")
                        
                        time.sleep(1.5)
                        
                        detail_soup = BeautifulSoup(driver.page_source, "html.parser")

                        try:
                            salario_tag = detail_soup.select_one('div[role="group"][aria-label="Salário"] span')
                            if salario_tag:
                                job_salario = limpar_texto(salario_tag.get_text())
                        except Exception:
                            pass

                        try:
                            tipo_tag = detail_soup.select_one('div[role="group"][aria-label="Tipo de vaga"] span')
                            if tipo_tag:
                                job_tipo = limpar_texto(tipo_tag.get_text())
                        except Exception:
                            pass

                        try:
                            job_requisitos = extrair_requisicoes(detail_soup)
                        except Exception as e:
                            print(f"        Erro ao extrair requisitos: {e}")
                            job_requisitos = "Não informado"

                        try:
                            desc_tag = detail_soup.select_one("div#jobDescriptionText")
                            if not desc_tag:
                                desc_tag = detail_soup.select_one("div.jobsearch-jobDescriptionText")
                            if not desc_tag:
                                desc_tag = detail_soup.select_one("div[class*='jobDescriptionText']")
                            if not desc_tag:
                                desc_tag = detail_soup.select_one("div.jobsearch-JobComponent-description")
                            
                            if desc_tag:
                                job_description = limpar_texto(desc_tag.get_text())
                        except Exception:
                            pass

                        try:
                            beneficios_tag = detail_soup.select_one("div#benefits ul")
                            if beneficios_tag:
                                beneficios_items = beneficios_tag.find_all('li')
                                job_beneficios = " | ".join([limpar_texto(b.get_text()) for b in beneficios_items])
                        except Exception:
                            pass
                        
                        print(f"        ✓ Detalhes extraídos com sucesso")

                    except TimeoutException:
                        print(f"        ⚠ Timeout ao carregar detalhes - tentando extrair mesmo assim")
                        try:
                            detail_soup = BeautifulSoup(driver.page_source, "html.parser")
                            
                            desc_tag = detail_soup.select_one("div#jobDescriptionText")
                            if not desc_tag:
                                desc_tag = detail_soup.select_one("div.jobsearch-jobDescriptionText")
                            if not desc_tag:
                                desc_tag = detail_soup.select_one("div[class*='jobDescriptionText']")
                            
                            if desc_tag:
                                job_description = limpar_texto(desc_tag.get_text())
                                print(f"        ✓ Descrição extraída após timeout")
                        except:
                            pass
                    except Exception as e:
                        print(f"        ⚠ Erro ao extrair detalhes: {type(e).__name__}")
                    
                except NoSuchWindowException as e:
                    print(f"        ✗ Erro ao gerenciar janelas: {e}")
                except WebDriverException as e:
                    print(f"        ✗ Erro no WebDriver: {type(e).__name__}")
                except Exception as e:
                    print(f"        ✗ Erro inesperado: {type(e).__name__} - {str(e)[:100]}")
                finally:
                    try:
                        if len(driver.window_handles) > 1:
                            driver.close()
                        driver.switch_to.window(original_window)
                    except Exception as e:
                        print(f"        ⚠ Erro ao fechar aba: {type(e).__name__}")
                        try:
                            driver.switch_to.window(original_window)
                        except:
                            pass

            results.append({
                'titulo_vaga': job_title,
                'empresa': company_name,
                'localizacao': job_location,
                'salario': job_salario,
                'descricao': job_description,
                'requisitos': job_requisitos,
                'beneficios': job_beneficios,
                'tipo_contrato': job_tipo,
                'modalidade': job_modalidade,
                'data_publicacao': data_publicacao,
                'url_vaga': job_url,
                'fonte': 'Indeed.com',
                'palavra_chave': keyword
            })
            time.sleep(1)

    driver.quit()
    return results

def salvar_vagas_supabase(conn, vagas, lote_size=50):
    """Salva as vagas coletadas no Supabase em lotes com tratamento de duplicatas"""
    
    if not vagas:
        print("⚠️  Nenhuma vaga para salvar")
        return
    
    sql_insert = """
    INSERT INTO vagas_emprego (
        titulo_vaga, empresa, localizacao, salario, descricao, 
        requisitos, beneficios, tipo_contrato, modalidade, 
        data_publicacao, url_vaga, fonte
    ) VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
    ) ON CONFLICT (url_vaga) DO NOTHING;
    """
    
    sql_check = "SELECT COUNT(*) FROM vagas_emprego WHERE url_vaga = %s;"
    
    vagas_salvas = 0
    vagas_duplicadas = 0
    vagas_erro = 0
    
    print(f"💾 Processando {len(vagas)} vagas em lotes de {lote_size}...")
    
    for i, vaga in enumerate(vagas, 1):
        try:
            # Verifica se a conexão está ativa e reconecta se necessário
            if conn.closed:
                print("  🔄 Reconectando ao banco...")
                conn = conectar_banco()
                if not conn:
                    print("  ❌ Não foi possível reconectar")
                    return
            
            cursor = conn.cursor()
            
            # Verifica duplicata
            cursor.execute(sql_check, (vaga['url_vaga'],))
            existe = cursor.fetchone()[0] > 0
            
            if existe:
                vagas_duplicadas += 1
                print(f"  🔄 ({i}/{len(vagas)}) Vaga já existe: {vaga['titulo_vaga']}")
                cursor.close()
                continue
            
            # Insere vaga
            cursor.execute(sql_insert, (
                vaga['titulo_vaga'],
                vaga['empresa'],
                vaga['localizacao'],
                vaga['salario'],
                vaga['descricao'],
                vaga['requisitos'],
                vaga['beneficios'],
                vaga['tipo_contrato'],
                vaga['modalidade'],
                vaga['data_publicacao'],
                vaga['url_vaga'],
                vaga['fonte']
            ))
            
            if cursor.rowcount > 0:
                vagas_salvas += 1
                print(f"  ✅ ({i}/{len(vagas)}) Nova vaga salva: {vaga['titulo_vaga']}")
            else:
                vagas_duplicadas += 1
            
            cursor.close()
            
            # Commit a cada lote ou na última vaga
            if i % lote_size == 0 or i == len(vagas):
                conn.commit()
                print(f"  💾 Commit realizado ({i}/{len(vagas)} vagas processadas)")
            
        except psycopg2.OperationalError as e:
            print(f"  ⚠️ Erro de conexão: {e}")
            print("  🔄 Tentando reconectar...")
            try:
                conn = conectar_banco()
                if conn:
                    print("  ✅ Reconectado com sucesso")
                    # Tenta salvar a vaga novamente
                    cursor = conn.cursor()
                    cursor.execute(sql_insert, (
                        vaga['titulo_vaga'], vaga['empresa'], vaga['localizacao'],
                        vaga['salario'], vaga['descricao'], vaga['requisitos'],
                        vaga['beneficios'], vaga['tipo_contrato'], vaga['modalidade'],
                        vaga['data_publicacao'], vaga['url_vaga'], vaga['fonte']
                    ))
                    conn.commit()
                    cursor.close()
                    vagas_salvas += 1
                    print(f"  ✅ Vaga salva após reconexão")
                else:
                    vagas_erro += 1
            except Exception:
                vagas_erro += 1
                
        except Exception as e:
            print(f"  ❌ ({i}/{len(vagas)}) Erro ao salvar '{vaga['titulo_vaga'][:50]}...': {str(e)[:100]}")
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
    """Verifica quantas vagas foram salvas no total"""
    try:
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM vagas_emprego;")
        total_geral = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM vagas_emprego WHERE fonte = 'Indeed.com';")
        total_indeed = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT titulo_vaga, empresa, localizacao, modalidade, data_coleta 
            FROM vagas_emprego 
            WHERE fonte = 'Indeed.com'
            ORDER BY data_coleta DESC 
            LIMIT 5;
        """)
        
        ultimas_vagas = cursor.fetchall()
        
        print(f"\n📊 ESTATÍSTICAS DO BANCO:")
        print(f"   Total de vagas (geral): {total_geral}")
        print(f"   Total do Indeed: {total_indeed}")
        
        if ultimas_vagas:
            print(f"\n📋 Últimas 5 vagas do Indeed:")
            for vaga in ultimas_vagas:
                print(f"   • {vaga[0]} - {vaga[1]} ({vaga[2]}) - {vaga[3]}")
        
        cursor.close()
        
    except Exception as e:
        print(f"❌ Erro ao verificar vagas salvas: {e}")

# ========== CONFIGURAÇÃO DAS PALAVRAS-CHAVE ==========

KEYWORDS = [
    "Desenvolvedor Python",
    "Analista de Dados",
    "Cientista de Dados",
    "Engenheiro de Software",
    "Desenvolvedor Full Stack",
    "Analista de BI",
    "DevOps",
    "Cientista da Computação"
]

LOCATION = "São Paulo, SP"
MAX_PAGES = 3

# ======================================================

print(f"=== Iniciando busca de vagas no Indeed ===")
print(f"Localização: {LOCATION}")
print(f"Palavras-chave: {len(KEYWORDS)}")
print(f"Páginas por busca: {MAX_PAGES}")
print("=" * 50)

# Conecta ao banco
conn = conectar_banco()
if not conn:
    print("❌ Não foi possível conectar ao banco. Encerrando.")
    exit()

try:
    # Estado inicial do banco
    print(f"\n📊 ESTADO INICIAL DO BANCO:")
    verificar_vagas_salvas(conn)
    
    all_data = []

    for idx, keyword in enumerate(KEYWORDS, 1):
        print(f"\n[{idx}/{len(KEYWORDS)}] Buscando por: '{keyword}'")
        print("-" * 50)
        
        try:
            data = scrape_indeed(keyword, LOCATION, max_pages=MAX_PAGES)
            all_data.extend(data)
            print(f"✓ Encontradas {len(data)} vagas para '{keyword}'")
            
            if idx < len(KEYWORDS):
                wait_time = 5
                print(f"Aguardando {wait_time} segundos antes da próxima busca...")
                time.sleep(wait_time)
                
        except Exception as e:
            print(f"✗ Erro ao buscar '{keyword}': {e}")
            continue

    print("\n" + "=" * 50)
    print(f"Total de vagas coletadas: {len(all_data)}")

    if all_data:
        print(f"\n💾 SALVANDO NO SUPABASE...")
        conn = salvar_vagas_supabase(conn, all_data)
        
        # Verifica se a conexão ainda está ativa
        if conn and not conn.closed:
            print(f"\n📊 ESTADO FINAL DO BANCO:")
            verificar_vagas_salvas(conn)
        else:
            print(f"\n⚠️  Conexão perdida. Reconectando para verificar estado final...")
            conn = conectar_banco()
            if conn:
                verificar_vagas_salvas(conn)
    else:
        print("⚠️  Nenhuma vaga foi coletada.")

except KeyboardInterrupt:
    print(f"\n⏹️  Scraping interrompido pelo usuário.")
except Exception as e:
    print(f"\n❌ Erro geral no scraping: {e}")

finally:
    if conn and not conn.closed:
        conn.close()
        print(f"\n🔌 Conexão com banco fechada.")
    else:
        print(f"\n⚠️  Conexão já estava fechada.")
    print("=" * 50)
    print("✅ SCRAPING FINALIZADO!")