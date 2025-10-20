import time
import random
import re
from datetime import datetime, timedelta, date
import psycopg2
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
import undetected_chromedriver as uc

from urllib.parse import urljoin, urlparse
import json
from pathlib import Path
from groq import Groq
from urllib.parse import urlsplit, urlunsplit, urljoin, quote, unquote, urlparse

CONNECTION_STRING = "postgresql://postgres.wnhqaiogzvvwrxcgfwsj:abkm@aws-1-sa-east-1.pooler.supabase.com:5432/postgres"

CHECKPOINT_ARQ = Path("vagas_empregos2.jsonl")


class EmpregosComBrScraper:
    def __init__(self, headless=False):
        """Inicializa o scraper com Selenium"""
        self.driver = None
        self.wait = None
        self.setup_driver(headless)
        
    def setup_driver(self, headless=False):
        """Configura o driver com undetected-chromedriver, usando apenas as opções necessárias."""
        
        chrome_options = uc.ChromeOptions()
        
        # Apenas as opções essenciais. As opções experimentais foram removidas.
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--no-sandbox")
        
        # User agent realista
        chrome_options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')
        
        if headless:
            print("⚠️ Executando em modo headless. Se ocorrerem erros, tente em modo visual (headless=False).")
            chrome_options.add_argument('--headless=new')
        
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument('--start-maximized')
        
        try:
            print("🚀 Usando undetected-chromedriver com opções limpas...")
            # A chamada para criar o driver continua a mesma
            self.driver = uc.Chrome(options=chrome_options, use_subprocess=True)
            
            # Aumentamos a paciência do scraper, já que o site é lento
            self.wait = WebDriverWait(self.driver, 25) 
            print("✅ Driver undetected-chromedriver configurado com sucesso!")

        except Exception as e:
            print(f"❌ Erro ao configurar driver: {e}")
            print("💡 Dica: Certifique-se de que a biblioteca 'undetected-chromedriver' está instalada (`pip install undetected-chromedriver`).")
            raise
    
    def conectar_banco(self):
        """Conecta ao banco PostgreSQL do Supabase"""
        try:
            conn = psycopg2.connect(CONNECTION_STRING)
            print("✅ Conectado ao Supabase com sucesso!")
            return conn
        except Exception as e:
            print(f"❌ Erro na conexão: {e}")
            return None
    
    def limpar_texto(self, texto):
        if not texto:
            return "Não informado"
        texto = re.sub(r'\s+', ' ', texto.strip())
        # remove caracteres de controle/invisíveis comuns
        texto = re.sub(r'[\u200B-\u200D\uFEFF]', '', texto)
        return texto or "Não informado"
    
    def aguardar_elemento(self, locator, timeout=10):
        """Aguarda um elemento aparecer na página"""
        try:
            element = WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located(locator)
            )
            return element
        except TimeoutException:
            return None
    
    def scroll_para_elemento(self, elemento):
        """Faz scroll até o elemento"""
        try:
            self.driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", elemento)
            time.sleep(0.5)
        except:
            pass
    
    def clicar_com_javascript(self, elemento):
        """Clica no elemento usando JavaScript"""
        try:
            self.driver.execute_script("arguments[0].click();", elemento)
            return True
        except:
            return False
    
    def extrair_modalidade(self, modalidade):
        """Extrai a modalidade de trabalho do texto"""
        texto_lower = modalidade.lower()
        
        # Padrões para identificar modalidade
        if any(termo in texto_lower for termo in ['home office', 'remoto', 'remota', '100% remoto', 'trabalho remoto', 'anywhere']):
            return "Remoto"
        elif any(termo in texto_lower for termo in ['híbrido', 'hibrido', 'misto', 'flexível', 'flexivel', 'home office parcial']):
            return "Híbrido"
        elif any(termo in texto_lower for termo in ['presencial', 'escritório', 'escritorio', 'on-site', 'on site']):
            return "Presencial"
        
        return "Não informado"
    
    def extrair_salario(self, texto):
        """Extrai informação de salário do texto"""
        texto_lower = texto.lower()
        
        # Busca por padrões de salário
        padroes_salario = [
            r'r\$\s*[\d\.,]+(?:\s*a\s*r\$\s*[\d\.,]+)?',  # R$ 1.000 a R$ 2.000
            r'salário:\s*r\$\s*[\d\.,]+',  # Salário: R$ 1.000
            r'remuneração:\s*r\$\s*[\d\.,]+',  # Remuneração: R$ 1.000
            r'de\s+r\$\s*[\d\.,]+\s+a\s+r\$\s*[\d\.,]+',  # de R$ 1.000 a R$ 2.000
        ]
        
        for padrao in padroes_salario:
            match = re.search(padrao, texto_lower)
            if match:
                return self.limpar_texto(match.group())
        
        if 'a combinar' in texto_lower or 'à combinar' in texto_lower:
            return "A combinar"
        
        return "Não informado"
    
    def extrair_requisitos(self, texto_completo):
        """Extrai requisitos da vaga"""
        if not texto_completo:
            return "Não informado"
        
        texto_lower = texto_completo.lower()
        requisitos = []
        
        # Padrões para encontrar seção de requisitos
        padroes_inicio = [
            'requisitos:', 'requisitos necessários:', 'perfil desejado:',
            'o que esperamos:', 'você precisa ter:', 'experiência necessária:',
            'qualificações:', 'habilidades necessárias:', 'pré-requisitos:',
            'conhecimentos necessários:', 'formação:', 'cursos:', 'curso:',
            'hard skills:', 'soft skills:', 'o que buscamos:',
            'exigimos:', 'necessário conhecimento em:',
            'o que você precisa:', 'seu papel será:', 'quem é você:',
            'necessário:', 'exigências:', 'o candidato deve:',
            'experiência mínima:', 'experiência desejada:',
            'conhecimentos técnicos:', 'stack necessária:'
        ]
        
        # Padrões de fim de seção
        padroes_fim = [
            'benefícios:', 'o que oferecemos:', 'diferenciais:',
            'sobre a empresa:', 'atividades:', 'responsabilidades:',
            'local de trabalho:', 'tipo de contrato:', 'salário:',
            'remuneração:', 'carga horária:', 'modalidade:',
            'o que temos para você:', 'contratação:',
            'nossos benefícios:', 'atrativos:', 'vantagens:',
            'detalhes da vaga:', 'informações adicionais:',
            'sobre nós:', 'nossa cultura:', 'como se candidatar:'
        ]
        
        melhor_inicio = -1
        padrao_encontrado = None
        
        # Encontra o início da seção de requisitos
        for padrao in padroes_inicio:
            pos = texto_lower.find(padrao)
            if pos != -1 and (melhor_inicio == -1 or pos < melhor_inicio):
                melhor_inicio = pos
                padrao_encontrado = padrao
        
        if melhor_inicio != -1:
            # Encontra o fim da seção
            fim_secao = melhor_inicio + 1000  # Máximo de 1000 caracteres
            
            for padrao_fim in padroes_fim:
                pos_fim = texto_lower.find(padrao_fim, melhor_inicio + len(padrao_encontrado))
                if pos_fim != -1 and pos_fim < fim_secao:
                    fim_secao = pos_fim
            
            texto_requisitos = texto_completo[melhor_inicio:fim_secao]
            
            # Remove o padrão inicial
            if padrao_encontrado:
                texto_requisitos = texto_requisitos.replace(padrao_encontrado, '', 1)
                texto_requisitos = texto_requisitos.replace(padrao_encontrado.capitalize(), '', 1)
            
            texto_requisitos = self.limpar_texto(texto_requisitos)
            
            if len(texto_requisitos) > 20:
                return texto_requisitos
        
        # Busca alternativa por palavras-chave
        palavras_chave = ['formação', 'graduação', 'experiência', 'conhecimento', 'inglês', 'excel', 'pacote office']
        for palavra in palavras_chave:
            if palavra in texto_lower:
                # Extrai a frase que contém a palavra
                sentences = re.split(r'[.\n]', texto_completo)
                for sentence in sentences:
                    if palavra in sentence.lower():
                        requisitos.append(sentence.strip())
        
        if requisitos:
            return self.limpar_texto('. '.join(requisitos[:5]))  # Máximo 5 frases
        
        return "Não informado"
    
    BASE = "https://www.empregos.com.br"

    def _normalize_url(self, u: str) -> str | None:
        if not u:
            return None
        u = u.strip()

        # ignora anchors e javascript:
        if u.startswith("#") or u.lower().startswith("javascript:"):
            return None

        # torna absoluta
        if u.startswith("/"):
            u = urljoin(self.BASE, u)
        elif not urlparse(u).scheme:
            u = urljoin(self.BASE + "/", u)

        # codifica corretamente path e query (acentos, espaços etc.)
        sp = urlsplit(u)
        path = quote(unquote(sp.path))                  # /vaga/Desenvolvedor ... -> /vaga/Desenvolvedor%20...
        query = quote(unquote(sp.query), safe="=&?/%:+")# mantém separadores
        frag = quote(unquote(sp.fragment), safe="=&?/%:+")
        return urlunsplit((sp.scheme, sp.netloc, path, query, frag))

    def processar_vaga_listagem(self, vaga_element):
        """Processa uma vaga da listagem (extraindo URL sem depender de clique real)."""
        try:
            vaga_info = {}

            # Título
            try:
                titulo_elem = vaga_element.find_element(By.XPATH, ".//span[contains(@class, 'text-base') and contains(@class, 'text-cinza90')]")
                vaga_info['titulo_vaga'] = titulo_elem.text
            except:
                vaga_info['titulo_vaga'] = "Não informado"
                print("Erro ao adquirir o titulo.")

            # Empresa
            try:
                empresa_elem = vaga_element.find_element(By.XPATH, "( .//a[contains(@class,'text-ciano100') and contains(@class,'text-sm')] )[2]")
                vaga_info['empresa'] = empresa_elem.text
            except:
                vaga_info['empresa'] = "Não informado"
                print("Erro ao adquirir a empresa.")

            # Localização
            try:
                local_elem = vaga_element.find_element(By.XPATH, "(.//h3[@title])[1]")
                titulo = local_elem.get_attribute("title") or local_elem.text
                vaga_info['localizacao'] = titulo
            except:
                vaga_info['localizacao'] = "Não informado"
                print("Erro ao adquirir a localização.")

            # Data
            try:
                data_elem = vaga_element.find_element(By.XPATH, ".//h3[starts-with(text(), 'Publicada ')]")
                vaga_info['data_publicacao'] = self.processar_data(data_elem.text)
            except:
                vaga_info['data_publicacao'] = datetime.now().date()
                print("Erro ao adquirir a data.")

            # ===== URL real da vaga (sem clicar) =====
            try:
                # 1) Tenta achar um <a href="/vaga/...">
                url_vaga = self.driver.execute_script("""
                    const card = arguments[0];
                    // 1) link direto
                    let a = card.querySelector('a[href*="/vaga/"]');
                    if (a && a.href) return a.href;

                    // 2) atributos data-href no botão, no card, ou pais
                    const btn = card.querySelector('span,button,[role="button"]');
                    const probe = el => el && (el.getAttribute('data-href') || el.dataset?.href || el.getAttribute('data-url') || el.dataset?.url);
                    let dh = probe(btn) || probe(card) || probe(card.parentElement);
                    if (dh) {
                        try { return new URL(dh, location.origin).href; } catch(e) { /* tenta bruto */ return dh; }
                    }

                    // 3) onclick com URL
                    const attrs = [btn, card, card.parentElement].filter(Boolean);
                    for (const el of attrs) {
                        const oc = el.getAttribute && (el.getAttribute('onclick') || '');
                        if (oc) {
                            // procura "http(s)://.../vaga/...."
                            const m = oc.match(/https?:\\/\\/[^'"]*\\/vaga\\/[^'"]+/);
                            if (m) return m[0];
                            // ou '/vaga/...' relativo
                            const m2 = oc.match(/['"]?(\\/vaga\\/[^'"]+)['"]?/);
                            if (m2) { try { return new URL(m2[1], location.origin).href; } catch(e) { return m2[1]; } }
                        }
                    }

                    // 4) Às vezes o card tem um ID com número da vaga; se houver,
                    //    mas sem slug, NÃO retornamos aqui (pois você disse que precisa do slug).
                    //    Então apenas null e deixamos o fallback do hook rodar abaixo no Python.
                    return null;
                """, vaga_element)

                # 4) Fallback: hookar window.open, clicar e capturar a URL sem abrir popup real
                if not url_vaga:
                    try:
                        link_elem = vaga_element.find_element(By.XPATH, ".//span[normalize-space()='Mais detalhes']")
                    except:
                        link_elem = None

                    if link_elem:
                        # injeta hook no window.open (não abre popup, só capta a URL)
                        self.driver.execute_script("""
                            window._capturedOpen = null;
                            (function(){
                                const _open = window.open;
                                window.open = function(u,n,s){
                                    try { window._capturedOpen = u; } catch(e) {}
                                    return null; // impede popup
                                };
                            })();
                        """)
                        # rola e clica
                        self.scroll_para_elemento(link_elem)
                        self.clicar_com_javascript(link_elem)
                        time.sleep(0.8)
                        # lê URL capturada
                        url_vaga = self.driver.execute_script("return window._capturedOpen;")

                if url_vaga and '/vaga/' in (url_vaga or ''):
                    url_vaga = self._normalize_url(url_vaga)
                    vaga_info['url_vaga'] = url_vaga
                    print("URL da vaga:", url_vaga)
                else:
                    vaga_info['url_vaga'] = None
                    print("⚠️ Não consegui extrair a URL da vaga sem href/slug.")

            except Exception as e:
                vaga_info['url_vaga'] = None
                print("Erro ao extrair URL da vaga:", e)

            return vaga_info

        except Exception as e:
            print(f"  ⚠️ Erro ao processar vaga da listagem: {e}")
            return None

    # def limpar_abas_extras(self):
    #     """Fecha todas as abas extras, mantendo apenas a principal"""
    #     try:
    #         abas = self.driver.window_handles
    #         if len(abas) > 1:
    #             aba_principal = abas[0]
    #             for aba in abas[1:]:
    #                 try:
    #                     self.driver.switch_to.window(aba)
    #                     self.driver.close()
    #                 except:
    #                     pass
    #             self.driver.switch_to.window(aba_principal)
    #             print("  🧹 Abas extras limpas")
    #     except Exception as e:
    #         print(f"  ⚠️ Erro ao limpar abas: {e}")


    def processar_data(self, texto_data: str):
        base = datetime.now().date()
        t = (texto_data or "").strip().lower()

        if re.search(r"\b(hoje|today|agora|minutos?|horas?)\b", t):
            return base
        if re.search(r"\b(ontem|yesterday)\b", t):
            return base - timedelta(days=1)

        m = re.search(r"h[aá]\s*(\d+)\s*dias?", t)
        if m:
            return base - timedelta(days=int(m.group(1)))

        return base  # fallback


    def _esperar_carregamento_detalhes(self, expected_title=None, timeout=25):
        """
        Espera de forma robusta pelo carregamento da página de detalhes.
        1. Aguarda o CONTAINER DA DESCRIÇÃO aparecer. É a melhor prova de que a vaga carregou.
        2. Valida o TÍTULO como uma checagem secundária.
        """
        try:
            # 1. PONTO CRÍTICO: Esperar pelo container da descrição.
            descricao_locator = (By.XPATH, ".//div[contains(@class, 'text-cinza90') and contains(@class, 'break-words')]")
            print("  ⏳ Aguardando container da descrição...")
            WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located(descricao_locator)
            )
            print("  ✅ Container da descrição carregado.")

            # 2. CHECAGEM SECUNDÁRIA: Validar o título para ter 100% de certeza.
            if expected_title:
                titulo_locator = (By.XPATH, "//h1[contains(@class,'text-') or contains(@class,'font-')][1]")
                titulo_atual = self.driver.find_element(*titulo_locator).text.strip()

                t_esperado = re.sub(r'\s+', ' ', expected_title.lower())
                t_atual = re.sub(r'\s+', ' ', titulo_atual.lower())
                
                palavras_esperadas = set(t_esperado.split())
                palavras_atuais = set(t_atual.split())
                
                if not palavras_esperadas.intersection(palavras_atuais):
                    print(f"  ⚠️ Título não corresponde! Esperado: '{expected_title}', Encontrado: '{titulo_atual}'")
                    raise TimeoutException("Título não correspondeu após carregamento do conteúdo.")
            
            print(f"  ✅ Título validado: '{titulo_atual}'")
            return True

        except TimeoutException:
            print("  ❌ Timeout: Conteúdo principal da vaga não carregou a tempo.")
            return False
    
    def acessar_detalhes_vaga(self, url_vaga, max_tentativas=3, expected_title=None):
        """Versão super robusta para sites lentos e com proteção."""
        url_vaga = self._normalize_url(url_vaga)
        if not url_vaga:
            print("  ⚠️ URL inválida após normalização; pulando...")
            return {}
        
        for tentativa in range(max_tentativas):
            try:
                print(f"  🔍 Acessando: {url_vaga} (tentativa {tentativa + 1}/{max_tentativas})")
                
                # Damos mais tempo para a página carregar, pois sabemos que é lenta
                self.driver.set_page_load_timeout(45)
                try:
                    self.driver.get(url_vaga)
                except TimeoutException:
                    print("  ⚠️ Timeout de carregamento inicial (normal para este site). Validando conteúdo...")
                    try:
                        self.driver.execute_script("window.stop();")
                    except WebDriverException:
                        pass

                # 🔴 USA A NOVA VALIDAÇÃO ROBUSTA 🔴
                if not self._esperar_carregamento_detalhes(expected_title):
                    if tentativa < max_tentativas - 1:
                        print("  🔄 Falha na validação. Tentando atualizar a página...")
                        self.driver.refresh()
                        time.sleep(3)
                        continue
                    else:
                        print("  ❌ Desistindo da vaga após múltiplas falhas de validação.")
                        return {}

                # --- EXTRAÇÃO SEGURA ---
                # Se chegamos aqui, a página carregou corretamente.
                detalhes = {}
                
                # Usamos o mesmo seletor da validação para garantir consistência
                descricao_elem = self.driver.find_element(By.XPATH, ".//div[contains(@class, 'text-cinza90') and contains(@class, 'break-words')]")
                detalhes['descricao'] = self.limpar_texto(descricao_elem.text)
                
                texto_completo = detalhes.get('descricao', '')

                # Outros campos
                try:
                    modalidade = self.driver.find_element(By.XPATH, ".//p[normalize-space(text())='Tipo de vaga']/following-sibling::h3").text
                    detalhes['modalidade'] = self.extrair_modalidade(modalidade)
                except: detalhes['modalidade'] = "Não informado"
                
                try:
                    salario = self.driver.find_element(By.XPATH, ".//p[normalize-space(text())='Remuneração']/following-sibling::h3").text
                    detalhes['salario'] = self.extrair_salario(salario)
                except: detalhes['salario'] = "Não informado"
                
                detalhes['requisitos'] = self.extrair_requisitos(texto_completo)
                detalhes['beneficios'] = self.extrair_beneficios(texto_completo)
                detalhes['tipo_contrato'] = self.extrair_tipo_contrato(texto_completo)

                return detalhes

            except Exception as e:
                print(f"  ❌ Erro inesperado na tentativa {tentativa + 1}: {type(e).__name__} - {e}")
                if tentativa < max_tentativas - 1:
                    time.sleep(3)
                    continue
                return {}
        return {}
        

    
    def extrair_beneficios(self, texto_completo):
        """Extrai benefícios da vaga"""
        if not texto_completo:
            return "Não informado"
        
        texto_lower = texto_completo.lower()
        beneficios = []
        
        # Padrões para encontrar benefícios
        padroes_inicio = [
            # Mais comuns
            'benefícios:', 'beneficios:', 'nossos benefícios:',
            'o que oferecemos:', 'oferecemos:', 'vantagens:',

            # Variações frequentes
            'o que você vai receber:', 'o que você terá direito:',
            'o que proporcionamos:', 'temos para você:', 'aqui você encontra:',
            'o que disponibilizamos:', 'o que garantimos:', 'o que a empresa oferece:',

            # Outras variações vistas em TI
            'o que temos para oferecer:', 'benefícios inclusos:',
            'perks:', 'regalias:', 'nossos diferenciais:',
            'pacote de benefícios:', 'atrativos:', 'nossos atrativos:',
            'ofertas para você:', 'o que você ganha:'
        ]
        
        melhor_inicio = -1
        padrao_encontrado = None
        
        for padrao in padroes_inicio:
            pos = texto_lower.find(padrao)
            if pos != -1 and (melhor_inicio == -1 or pos < melhor_inicio):
                melhor_inicio = pos
                padrao_encontrado = padrao
        
        if melhor_inicio != -1:
            # Extrai até 800 caracteres após o padrão
            fim_secao = melhor_inicio + 800
            
            # Padrões de fim
            padroes_fim = [
                # Seções clássicas
                'requisitos:', 'atividades:', 'responsabilidades:',
                'sobre a empresa:', 'local de trabalho:', 'tipo de contrato:',
                'salário:', 'remuneração:', 'carga horária:', 'modalidade:',

                # Jeitos diferentes que empresas usam
                'o que esperamos:', 'diferenciais:', 'o que buscamos:',
                'informações adicionais:', 'detalhes da vaga:',
                'nossa cultura:', 'sobre nós:', 'como se candidatar:',
                'contratação:', 'atrativos:', 'vantagens:',

                # Mais variações
                'perfil desejado:', 'o que você vai fazer:', 'missão do cargo:',
                'desafios:', 'seu dia a dia:', 'projeto:', 'stack:',
                'conhecimentos necessários:', 'exigências:', 'qualificações:',

                # Algumas empresas colocam seção final
                'etapas do processo seletivo:', 'processo seletivo:',
                'prazo de inscrição:', 'como aplicar:', 'candidate-se:',
                'envie seu currículo:', 'inscrições abertas:',

                # Outras âncoras comuns
                'o que oferecemos:', 'oferecemos:', 'nossos diferenciais:',
                'nossa equipe:', 'sobre a vaga:', 'detalhes adicionais:'
            ]
            for padrao_fim in padroes_fim:
                pos_fim = texto_lower.find(padrao_fim, melhor_inicio + len(padrao_encontrado))
                if pos_fim != -1 and pos_fim < fim_secao:
                    fim_secao = pos_fim
            
            texto_beneficios = texto_completo[melhor_inicio:fim_secao]
            
            # Remove o padrão inicial
            if padrao_encontrado:
                texto_beneficios = texto_beneficios.replace(padrao_encontrado, '', 1)
                texto_beneficios = texto_beneficios.replace(padrao_encontrado.capitalize(), '', 1)
            
            
            if len(texto_beneficios) > 20:
                return texto_beneficios
        
        # Busca por benefícios comuns
        beneficios_comuns = [
                # Financeiros
                'vale refeição', 'vale alimentação', 'vale transporte',
                'vale combustível', 'auxílio creche', 'auxílio educação',
                'auxílio home office', 'bônus', 'plr', 'ppr',
                'stock options', 'participação nos lucros', 'vale cultura',

                # Saúde
                'plano de saúde', 'plano odontológico', 'seguro de vida',
                'gympass', 'totalpass', 'wellhub', 'apoio psicológico',
                'convênio farmácia', 'telemedicina', 'assistência médica',

                # Trabalho e Flexibilidade
                'home office', 'híbrido', 'flexibilidade', 'day off',
                'auxílio cursos', 'auxílio certificações', 'inglês in-company',
                'jornada flexível', 'trabalho remoto', 'short friday',

                # Férias e Licenças
                'férias', 'décimo terceiro', '13º salário',
                'licença maternidade estendida', 'licença paternidade estendida',
                'banco de horas', 'folga compensatória', 'day off aniversário',

                # Cultura e Extras
                'no dress code', 'ambiente descontraído', 'happy hour',
                'brindes', 'kit onboarding', 'pet friendly',
                'programa de reconhecimento', 'mentoria interna'
        ]
        
        for beneficio in beneficios_comuns:
            if beneficio in texto_lower:
                beneficios.append(beneficio.capitalize())
        
        if beneficios:
            return '; '.join(beneficios)
        
        return "Não informado"
    
    def extrair_tipo_contrato(self, texto_completo):
        """Extrai tipo de contrato da vaga"""
        texto_lower = texto_completo.lower()
        
        # Padrões de contrato
        if 'clt' in texto_lower or 'carteira assinada' in texto_lower:
            return "CLT"
        elif 'pj' in texto_lower or 'pessoa jurídica' in texto_lower or 'pessoa juridica' in texto_lower:
            return "PJ"
        elif 'estágio' in texto_lower or 'estagio' in texto_lower or 'estagiário' in texto_lower:
            return "Estágio"
        elif 'trainee' in texto_lower:
            return "Trainee"
        elif 'temporário' in texto_lower or 'temporario' in texto_lower:
            return "Temporário"
        elif 'freelancer' in texto_lower or 'freela' in texto_lower:
            return "Freelancer"
        elif 'mei' in texto_lower:
            return "MEI"
        
        return "Não informado"
    

    @staticmethod
    def reset_checkpoint_jsonl(path=CHECKPOINT_ARQ):
        """Apaga o conteúdo do JSONL no início da execução"""
        with path.open("w", encoding="utf-8") as f:
            f.write("")  # limpa o arquivo    


    @staticmethod
    def salvar_checkpoint_jsonl(vaga, path=CHECKPOINT_ARQ):
        def default_converter(obj):
            if isinstance(obj, (datetime, date)):
                return obj.isoformat()  # "2025-09-21"
            raise TypeError(f"Type {type(obj)} not serializable")

        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(vaga, ensure_ascii=False, default=default_converter) + "\n")

    def _groq_is_ti(self, vaga: dict, model: str = "llama-3.3-70b-versatile", max_retries: int = 3) -> bool:
        """
        Retorna True se a vaga for de TI (Tecnologia da Informação), senão False.
        Usa título, descrição e campos auxiliares.
        """
        try:
            api_key = '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'
            if not api_key:
                print("⚠️ GROQ_API_KEY não configurada; usando fallback heurístico.")
                return self._heuristica_is_ti(vaga)

            client = Groq(api_key=api_key)

            system = (
                "Você é um classificador de vagas. "
                "Responda ESTRITAMENTE em JSON válido com o formato: {\"is_ti\": true|false}. "
                "Considere TI como desenvolvimento de software, dados/ML, DevOps/Cloud, QA, "
                "segurança, suporte/infra, redes, DBA, análise de sistemas, produto/UX de software. "
                "Não é TI: vagas administrativas/financeiras/comerciais, saúde, jurídico, RH (a menos que seja específico de TI), "
                "industrial/operacional não ligado a software/infra, professores de áreas não-TI, etc. "
                "Se não houver informação suficiente, responda {\"is_ti\": false}."
            )

            # Passamos só o essencial
            payload = {
                "titulo_vaga": vaga.get("titulo_vaga"),
                "descricao": vaga.get("descricao"),
                "empresa": vaga.get("empresa"),
                "localizacao": vaga.get("localizacao"),
                "tipo_contrato": vaga.get("tipo_contrato"),
                "modalidade": vaga.get("modalidade")
            }

            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": f"Classifique a vaga abaixo:\n{json.dumps(payload, ensure_ascii=False)}"}
            ]

            for attempt in range(1, max_retries + 1):
                try:
                    resp = client.chat.completions.create(
                        model=model,
                        messages=messages,
                        temperature=0,
                        response_format={"type": "json_object"},
                    )
                    content = resp.choices[0].message.content or "{}"
                    data = json.loads(content)
                    return bool(data.get("is_ti", False))
                except Exception as e:
                    print(f"⚠️ Groq erro (tentativa {attempt}/{max_retries}): {e}")
                    time.sleep(1.2 * attempt)

            # Se todas as tentativas falharem, caímos no fallback
            return self._heuristica_is_ti(vaga)

        except Exception as e:
            print("⚠️ Falha inesperada no classificador Groq:", e)
            return self._heuristica_is_ti(vaga)

    def _heuristica_is_ti(self, vaga: dict) -> bool:
        """
        Fallback ultra simples (local) caso Groq falhe ou não esteja configurado.
        """
        txt = " ".join([
            vaga.get("titulo_vaga") or "",
            vaga.get("descricao") or "",
            vaga.get("requisitos") or "",
            vaga.get("beneficios") or ""
        ]).lower()

        # Palavras-chave básicas de TI
        chaves = [
            "desenvolvedor", "programador", "software", "sistemas", "ti", "tecnologia da informação",
            "python", "java", "javascript", "react", "angular", "node", "php", "c#", "c++",
            "devops", "cloud", "aws", "azure", "gcp", "kubernetes", "docker",
            "dados", "data", "sql", "postgres", "mysql", "mongodb", "etl", "engenheiro de dados",
            "cientista de dados", "analista de dados", "machine learning", "ml", "ia", "inteligência artificial",
            "qa", "teste de software", "quality assurance", "segurança da informação", "redes", "infraestrutura",
            "dbA", "analista de sistemas", "product owner", "scrum master"
        ]
        return any(k in txt for k in chaves)     
        
    def coletar_vagas(self, url, max_paginas=3):
        """
        Versão Final Corrigida: Implementa a navegação humana e a paginação robusta via verificação de URL.
        """
        todas_vagas = []
        
        try:
            print(f"\n🌐 Acessando página de listagem inicial: {url}")
            self.driver.get(url)
            time.sleep(random.uniform(3, 5))

            try:
                self.driver.find_element(By.XPATH, "//button[contains(text(), 'Aceitar')]").click()
                print("🍪 Cookies aceitos.")
                time.sleep(random.uniform(1, 2))
            except:
                print("ℹ️ Banner de cookies não encontrado.")

            for pagina_atual in range(1, max_paginas + 1):
                print("=" * 60)
                print(f"📄 Processando a página de resultados Nº {pagina_atual}...")
                
                # Armazena a URL da página de listagem atual para voltar depois
                url_da_lista = self.driver.current_url

                WebDriverWait(self.driver, 30).until(EC.presence_of_all_elements_located((By.XPATH, "//div[contains(@id, 'job-card')]")))
                time.sleep(random.uniform(2, 4))

                cards = self.driver.find_elements(By.XPATH, "//div[contains(@id, 'job-card')]")
                num_vagas_na_pagina = len(cards)
                print(f"📋 Encontradas {num_vagas_na_pagina} vagas. Iniciando o processo de clique e volta...")

                # Usamos um loop de índice para não nos perdermos após voltar a página
                for i in range(num_vagas_na_pagina):
                    print("-" * 30)
                    print(f"  ➡️ Processando vaga {i + 1} de {num_vagas_na_pagina}...")
                    
                    vaga_info_basica = {}
                    
                    try:
                        # 1. REENCONTRA OS CARDS A CADA ITERAÇÃO! Essencial para evitar erros.
                        cards_atuais = self.driver.find_elements(By.XPATH, "//div[contains(@id, 'job-card')]")
                        if i >= len(cards_atuais):
                            print("  ⚠️ Card não encontrado, possivelmente um anúncio. Pulando.")
                            continue
                        
                        card_para_clicar = cards_atuais[i]
                        self.scroll_para_elemento(card_para_clicar)
                        time.sleep(0.5)

                        # 2. Extrai as infos básicas e a URL ANTES de clicar
                        titulo_elem = card_para_clicar.find_element(By.XPATH, ".//span[contains(@class, 'text-base')]")
                        vaga_info_basica['titulo_vaga'] = self.limpar_texto(titulo_elem.text)
                        vaga_info_basica['url_vaga'] = self._normalize_url(titulo_elem.find_element(By.XPATH, "./ancestor::a").get_attribute('href'))
                        
                        # Extrai o resto das infos básicas
                        try: vaga_info_basica['empresa'] = self.limpar_texto(card_para_clicar.find_element(By.XPATH, "( .//a[contains(@class,'text-ciano100')] )[2]").text)
                        except: vaga_info_basica['empresa'] = "Não informado"
                        try: vaga_info_basica['localizacao'] = self.limpar_texto(card_para_clicar.find_element(By.XPATH, "(.//h3[@title])[1]").get_attribute("title"))
                        except: vaga_info_basica['localizacao'] = "Não informado"
                        
                        # 3. CLICA para ir aos detalhes
                        print(f"  🖱️ Clicando em: {vaga_info_basica['titulo_vaga']}")
                        self.clicar_com_javascript(titulo_elem)

                        # 4. EXTRAI os detalhes da nova página
                        detalhes = self._extrair_informacoes_da_pagina_detalhes()
                        if not detalhes:
                            raise Exception("Falha ao extrair detalhes da vaga.")
                        
                        # 5. JUNTA TUDO
                        vaga_completa = {**vaga_info_basica, **detalhes, 'fonte': 'Empregos.com.br'}
                        
                        # 6. FILTRA E SALVA
                        if not self._heuristica_is_ti(vaga_completa):
                            print("  ⚠️ Vaga provavelmente não é de TI (heurística). Salvando para verificação posterior.")
                        
                        todas_vagas.append(vaga_completa)
                        self.salvar_checkpoint_jsonl(vaga_completa)
                        print(f"  💾 Vaga bruta '{vaga_completa['titulo_vaga']}' salva no JSON.")
                        
                    except Exception as e:
                        print(f"  ❌ Erro ao processar a vaga {i + 1}: {e}")
                    
                    finally:
                        # 7. VOLTA para a URL da lista (mais seguro que driver.back())
                        print(f"  ↩️ Retornando para a lista: {url_da_lista}")
                        self.driver.get(url_da_lista)
                        WebDriverWait(self.driver, 30).until(EC.presence_of_all_elements_located((By.XPATH, "//div[contains(@id, 'job-card')]")))
                        time.sleep(random.uniform(2, 4)) # Pausa importante

                # Fim do loop de vagas, agora vamos para a próxima página de resultados
                if pagina_atual < max_paginas:
                    print("-" * 30)
                    print(f"  ▶️ Tentando ir para a página de resultados {pagina_atual + 1}...")
                    try:
                        proxima_pagina_btn = self.driver.find_element(By.XPATH, "//a[contains(text(), 'Próxima')]")
                        self.clicar_com_javascript(proxima_pagina_btn)
                        
                        # 🔴 NOVA VERIFICAÇÃO ROBUSTA 🔴
                        nova_url_esperada = f"/{pagina_atual + 1}"
                        WebDriverWait(self.driver, 30).until(EC.url_contains(nova_url_esperada))
                        print(f"  ✅ Paginação bem-sucedida! URL agora contém '{nova_url_esperada}'.")
                        
                    except (NoSuchElementException, TimeoutException):
                        print("  ⏹️ Botão 'Próxima' não encontrado ou a página não carregou. Provavelmente é a última página.")
                        break # Encerra o loop de páginas para esta keyword
            
        except Exception as e:
            print(f"❌ Erro fatal na coleta: {e}")
        
        return todas_vagas
    
    @staticmethod
    def get_conn():
        return psycopg2.connect(
            CONNECTION_STRING,
            keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=5,
            options='-c statement_timeout=60000'  # 60s por comando
        )
    
    @staticmethod
    def _coerce_date(value):
        if not value or value == "Não informado":
            return None
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
                try:
                    return datetime.strptime(value, fmt).date()
                except:
                    pass
        return None
    
    # def salvar_vagas_supabase(self, conn, vagas):
    #     """Salva as vagas coletadas no Supabase"""
    #     if not vagas:
    #         print("⚠️  Nenhuma vaga para salvar")
    #         return
        
    #     try:
    #         cursor = conn.cursor()
            
    #         # SQL para inserir ignorando duplicatas
    #         sql_insert = """
    #         INSERT INTO vagas_emprego (
    #             titulo_vaga, empresa, localizacao, salario, descricao, 
    #             requisitos, beneficios, tipo_contrato, modalidade, 
    #             data_publicacao, url_vaga, fonte
    #         ) VALUES (
    #             %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
    #         ) ON CONFLICT (url_vaga) DO NOTHING;
    #         """
            
    #         vagas_salvas = 0
    #         vagas_duplicadas = 0
            
    #         print(f"\n💾 Salvando {len(vagas)} vagas no banco...")
            
    #         for i, vaga in enumerate(vagas, 1):
    #             try:
    #                 cursor.execute(sql_insert, (
    #                     vaga['titulo_vaga'],
    #                     vaga['empresa'],
    #                     vaga['localizacao'],
    #                     vaga['salario'],
    #                     vaga['descricao'][:5000],  # Limita descrição
    #                     vaga['requisitos'][:2000],  # Limita requisitos
    #                     vaga['beneficios'][:1000],  # Limita benefícios
    #                     vaga['tipo_contrato'],
    #                     vaga['modalidade'],
    #                     vaga['data_publicacao'],
    #                     vaga['url_vaga'],
    #                     vaga['fonte']
    #                 ))
                    
    #                 if cursor.rowcount > 0:
    #                     vagas_salvas += 1
    #                     print(f"  ✅ ({i}/{len(vagas)}) Salva: {vaga['titulo_vaga'][:50]}")
    #                 else:
    #                     vagas_duplicadas += 1
    #                     print(f"  🔄 ({i}/{len(vagas)}) Duplicada: {vaga['titulo_vaga'][:50]}")
                        
    #             except Exception as e:
    #                 print(f"  ❌ ({i}/{len(vagas)}) Erro: {e}")
    #                 conn.rollback()
    #                 continue
            
    #         conn.commit()
    #         cursor.close()
            
    #         print(f"\n✅ RESULTADO DO SALVAMENTO:")
    #         print(f"   📊 Vagas novas: {vagas_salvas}")
    #         print(f"   🔄 Duplicadas: {vagas_duplicadas}")
    #         print(f"   📈 Total processadas: {len(vagas)}")
            
    #     except Exception as e:
    #         print(f"❌ Erro ao salvar no banco: {e}")
    #         conn.rollback()

    def salvar_vagas_supabase(self, vagas, batch_size=200, max_retries=5):
        """
        Insere vagas em lotes com retry e reconexão automática.
        Usa ON CONFLICT (url_vaga) DO NOTHING para ignorar duplicadas.
        """
        if not vagas:
            print("⚠️ Nenhuma vaga para salvar")
            return

        sql_insert = """
            INSERT INTO vagas_emprego (
                titulo_vaga, empresa, localizacao, salario, descricao, 
                requisitos, beneficios, tipo_contrato, modalidade, 
                data_publicacao, url_vaga, fonte
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (url_vaga) DO NOTHING;
        """

        total = len(vagas)
        vagas_salvas = 0
        vagas_duplicadas = 0

        # conecta uma vez aqui; se cair, reconecta no retry
        conn = self.get_conn()
        cursor = conn.cursor()

        i = 0
        try:
            while i < total:
                lote = vagas[i:i + batch_size]
                tentativas = 0

                while True:
                    try:
                        for vaga in lote:
                            cursor.execute(sql_insert, (
                                vaga.get('titulo_vaga') or "",
                                vaga.get('empresa') or "",
                                vaga.get('localizacao') or "",
                                vaga.get('salario') or "",
                                (vaga.get('descricao') or "")[:5000],
                                (vaga.get('requisitos') or "")[:2000],
                                (vaga.get('beneficios') or "")[:1000],
                                vaga.get('tipo_contrato') or "Não informado",
                                vaga.get('modalidade') or "Não informado",
                                self._coerce_date(vaga.get('data_publicacao')),
                                vaga.get('url_vaga') or "",
                                vaga.get('fonte') or "Empregos.com.br"
                            ))
                            # psycopg2: rowcount = 1 quando inseriu; 0 quando DO NOTHING
                            if cursor.rowcount == 1:
                                vagas_salvas += 1
                            else:
                                vagas_duplicadas += 1

                        conn.commit()
                        print(f"  ✅ Lote {i+1}-{i+len(lote)} salvo")
                        break  # saiu do while True deste lote

                    except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
                        # conexão caiu → retry com reconexão
                        tentativas += 1
                        if tentativas > max_retries:
                            print(f"❌ Falha ao salvar lote após {max_retries} tentativas: {e}")
                            raise
                        print(f"⚠️ Conexão perdida. Tentando reconectar (tentativa {tentativas}/{max_retries})…")
                        # fecha e reconecta
                        try:
                            try:
                                cursor.close()
                            except:
                                pass
                            try:
                                conn.close()
                            except:
                                pass
                            time.sleep(2 * tentativas)  # backoff exponencial simples
                            conn = self.get_conn()
                            cursor = conn.cursor()
                        except Exception as e2:
                            print("❌ Erro ao reconectar:", e2)
                            time.sleep(2 * tentativas)
                            continue

                    except Exception as e:
                        # erro de dados → rollback do lote e tenta item a item
                        print(f"  ❌ Erro no lote {i+1}-{i+len(lote)}: {e}")
                        conn.rollback()
                        for vaga in lote:
                            try:
                                cursor.execute(sql_insert, (
                                    vaga.get('titulo_vaga') or "",
                                    vaga.get('empresa') or "",
                                    vaga.get('localizacao') or "",
                                    vaga.get('salario') or "",
                                    (vaga.get('descricao') or "")[:5000],
                                    (vaga.get('requisitos') or "")[:2000],
                                    (vaga.get('beneficios') or "")[:1000],
                                    vaga.get('tipo_contrato') or "Não informado",
                                    vaga.get('modalidade') or "Não informado",
                                    self._coerce_date(vaga.get('data_publicacao')),
                                    vaga.get('url_vaga') or "",
                                    vaga.get('fonte') or "Empregos.com.br"
                                ))
                                conn.commit()
                                if cursor.rowcount == 1:
                                    vagas_salvas += 1
                                else:
                                    vagas_duplicadas += 1
                            except Exception as e1:
                                conn.rollback()
                                # Loga a problemática e segue
                                print("    ⚠️ Falha nesta vaga (pulando):", vaga.get('url_vaga'), e1)
                        break  # saiu do while True deste lote

                i += len(lote)

        finally:
            try:
                cursor.close()
            except:
                pass
            try:
                conn.close()
            except:
                pass

        print(f"\n✅ RESULTADO DO SALVAMENTO:")
        print(f"   📊 Vagas novas: {vagas_salvas}")
        print(f"   🔄 Duplicadas: {vagas_duplicadas}")
        print(f"   📈 Total processadas: {total}")

        
    def verificar_estatisticas(self, conn):
        """Verifica estatísticas do banco"""
        try:
            cursor = conn.cursor()
            
            # Total de vagas do Empregos.com.br
            cursor.execute("SELECT COUNT(*) FROM vagas_emprego WHERE fonte = 'Empregos.com.br';")
            total_empregos = cursor.fetchone()[0]
            
            # Por modalidade
            cursor.execute("""
                SELECT modalidade, COUNT(*) 
                FROM vagas_emprego 
                WHERE fonte = 'Empregos.com.br'
                GROUP BY modalidade
                ORDER BY COUNT(*) DESC;
            """)
            modalidades = cursor.fetchall()
            
            print(f"\n📊 ESTATÍSTICAS EMPREGOS.COM.BR:")
            print(f"   Total de vagas: {total_empregos}")
            
            if modalidades:
                print(f"\n   Por modalidade:")
                for modalidade, total in modalidades:
                    print(f"   • {modalidade}: {total}")
            
            cursor.close()
            
        except Exception as e:
            print(f"❌ Erro ao verificar estatísticas: {e}")
    
    
    def executar_com_keywords(self, keywords_selecionadas=None):
        """Executa o scraping usando keywords específicas"""
        print("🚀 INICIANDO SCRAPING EMPREGOS.COM.BR COM KEYWORDS")
        print("=" * 60)
        
        self.reset_checkpoint_jsonl()
        
        # Lista completa de keywords
        todas_keywords = [
            # Programação Geral
            "desenvolvedor", "TI", "tecnologia", "it", "IT", "ti", 
            "tecnologia da informação", "sistemas", "engenheiro de software", 
            "dados", "inteligência de dados", "data",
            
            # Linguagens de Programação
            "python", "java", "javascript", "c++", "c#", "react", "angular", 
            "node", "laravel", "django",
            
            # Áreas de Desenvolvimento
            "full stack", "backend", "frontend", "mobile",
            
            # Data Science & Analytics
            "data scientist", "cientista de dados", "analista de dados", 
            "data analyst", "engenheiro de dados", "data engineer", 
            "machine learning", "ml", "deep learning", "ai", 
            "inteligência artificial", "big data", "analytics", 
            "analista de sistemas", "business intelligence", "bi", "BI",
            
            # Bancos de Dados
            "sql", "postgresql", "mysql", "mongodb", "nosql", "database", 
            "dba", "data warehouse", "snowflake",
            
            # Cloud & DevOps
            "devops", "cloud", "aws", "azure", "gcp", "google cloud", 
            "docker", "kubernetes"
        ]
        
        # Usa keywords selecionadas ou todas
        keywords = keywords_selecionadas if keywords_selecionadas else todas_keywords
        
        print(f"📋 Total de keywords para busca: {len(keywords)}")
        
        # Conecta ao banco
        conn = self.conectar_banco()
        if not conn:
            return
        
        try:
            # Mostra estatísticas iniciais
            self.verificar_estatisticas(conn)
            
            todas_vagas_coletadas = []
            
            # Processa cada keyword
            for idx, keyword in enumerate(keywords, 1):
                # Formata a keyword para URL (substitui espaços por hífen)
                keyword_url = keyword.replace(" ", "-").lower()
                url = f"https://www.empregos.com.br/vagas/{keyword_url}"
                
                print(f"\n🔍 [{idx}/{len(keywords)}] Buscando: {keyword}")
                print(f"   URL: {url}")
                print("-" * 40)
                
                vagas = self.coletar_vagas(url, max_paginas=4)  
                
                if vagas:
                    print(f"   ✅ {len(vagas)} vagas encontradas para '{keyword}'")
                    todas_vagas_coletadas.extend(vagas)
                else:
                    print(f"   ⚠️ Nenhuma vaga encontrada para '{keyword}'")
                
                # Pausa entre keywords
                if idx < len(keywords):
                    tempo_espera = random.uniform(3, 7)
                    print(f"   ⏱️ Aguardando {tempo_espera:.1f}s antes da próxima busca...")
                    time.sleep(tempo_espera)
            
            print(f"\n📈 RESULTADO GERAL:")
            print(f"   Total de keywords processadas: {len(keywords)}")
            print(f"   Total de vagas coletadas: {len(todas_vagas_coletadas)}")
            
            # Estatísticas por keyword
            if todas_vagas_coletadas:
                print("\n📊 Distribuição de vagas:")
                modalidades_count = {}
                contratos_count = {}
                
                for vaga in todas_vagas_coletadas:
                    # Conta modalidades
                    mod = vaga.get('modalidade', 'Não informado')
                    modalidades_count[mod] = modalidades_count.get(mod, 0) + 1
                    
                    # Conta tipos de contrato
                    cont = vaga.get('tipo_contrato', 'Não informado')
                    contratos_count[cont] = contratos_count.get(cont, 0) + 1
                
                print("\n   Por Modalidade:")
                for modalidade, count in sorted(modalidades_count.items(), key=lambda x: x[1], reverse=True):
                    print(f"   • {modalidade}: {count}")
                
                print("\n   Por Tipo de Contrato:")
                for contrato, count in sorted(contratos_count.items(), key=lambda x: x[1], reverse=True):
                    print(f"   • {contrato}: {count}")
                
                # Salva no banco
                print("\n💾 Salvando vagas no banco de dados...")
                self.salvar_vagas_supabase(todas_vagas_coletadas)
                
                # Mostra estatísticas finais
                self.verificar_estatisticas(conn)
            else:
                print("⚠️ Nenhuma vaga foi coletada")
                
        except KeyboardInterrupt:
            print("\n⏹️ Scraping interrompido pelo usuário")
        except Exception as e:
            print(f"\n❌ Erro durante execução: {e}")
        finally:
            conn.close()
            self.fechar()
            print("\n✅ SCRAPING FINALIZADO!")
            print("=" * 60)
    
    def fechar(self):
        """Fecha o driver do Selenium"""
        if self.driver:
            try:
                self.driver.quit()
                print("🔌 Driver fechado com sucesso")
            except:
                pass

def main():
    """Função principal com menu interativo"""
    print("=" * 60)
    print("🤖 SCRAPER EMPREGOS.COM.BR COM SELENIUM")
    print("=" * 60)
    
    print("\nEscolha o modo de execução:")
    print("1. Modo visual (abre navegador)")
    print("2. Modo headless (sem interface)")
    
    escolha_modo = input("\nDigite sua opção (1-2): ").strip()
    headless = escolha_modo == "2"
    
    print(f"\n{'🤖 Modo headless ativado' if headless else '👁️ Modo visual ativado'}")
    
    try:
        # Cria o scraper
        scraper = EmpregosComBrScraper(headless=headless)
            
        scraper.executar_com_keywords()
            
            
    except Exception as e:
        print(f"❌ Erro ao inicializar scraper: {e}")
        print("\n💡 Dicas:")
        print("   • Certifique-se de ter o Chrome instalado")
        print("   • Instale o ChromeDriver compatível")
        print("   • Verifique as dependências: selenium, psycopg2-binary")
        print("   • pip install selenium psycopg2-binary")

if __name__ == "__main__":
    # Importa biblioteca adicional necessária
    from datetime import timedelta
    
    main()