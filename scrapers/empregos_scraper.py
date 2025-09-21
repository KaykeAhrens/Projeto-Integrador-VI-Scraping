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
from urllib.parse import urljoin, urlparse
import json
from pathlib import Path


# 🔴 COLE SUA CONNECTION STRING AQUI (substitua a linha abaixo)
CONNECTION_STRING = "postgresql://postgres.wnhqaiogzvvwrxcgfwsj:abkm@aws-1-sa-east-1.pooler.supabase.com:5432/postgres"

CHECKPOINT_ARQ = Path("vagas_empregos.jsonl")


class EmpregosComBrScraper:
    def __init__(self, headless=False):
        """Inicializa o scraper com Selenium"""
        self.driver = None
        self.wait = None
        self.setup_driver(headless)
        
    def setup_driver(self, headless=False):
        """Configura o driver do Chrome"""
        chrome_options = Options()
        
        # Configurações para evitar detecção
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--no-sandbox")
        
        # User agent realista
        chrome_options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
        
        if headless:
            chrome_options.add_argument('--headless=new')
        
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument('--start-maximized')
        
        try:
            self.driver = webdriver.Chrome(options=chrome_options)
            self.wait = WebDriverWait(self.driver, 15)
            print("✅ Driver Chrome configurado com sucesso!")
        except Exception as e:
            print(f"❌ Erro ao configurar driver: {e}")
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
    


    
    def processar_vaga_listagem(self, vaga_element):
        """Processa uma vaga da listagem"""
        try:
            vaga_info = {}
            
            # Título da vaga
            try:
                titulo_elem = vaga_element.find_element(By.XPATH, ".//span[contains(@class, 'text-base') and contains(@class, 'text-cinza90')]")
                vaga_info['titulo_vaga'] = titulo_elem.text

                #print("Titulo adquirido.")
                
            except:
                vaga_info['titulo_vaga'] = "Não informado"
                print("Erro ao adquirir o titulo. ")

        
            # Link da Vaga 
            try:
                link_elem = vaga_element.find_element(By.XPATH, ".//span[text()='Mais detalhes']")
                link_elem.click()

                # Espera até abrir uma nova aba (timeout de 10s)
                WebDriverWait(self.driver, 10).until(lambda d: len(d.window_handles) > 1)

                abas = self.driver.window_handles
                self.driver.switch_to.window(abas[1])
                link_pagina = self.driver.current_url
                print("URL da vaga:", link_pagina)
                vaga_info['url_vaga'] = link_pagina

                self.driver.close()
                self.driver.switch_to.window(abas[0])
            except Exception as e:
                vaga_info['url_vaga'] = None
                print("Erro ao adquirir o link:", e)
            
            # Empresa
            try:
                empresa_elem = vaga_element.find_element(By.XPATH, "( .//a[contains(@class,'text-ciano100') and contains(@class,'text-sm')] )[2]")
                vaga_info['empresa'] = empresa_elem.text

                #print("empresa adquirida.")
            except:
                vaga_info['empresa'] = "Não informado"
                print("Erro ao adquirir a empresa. ")
            
            # Localização
            try:
                local_elem = vaga_element.find_element(By.XPATH, "(.//p[@title])[1]")
                titulo = local_elem.get_attribute("title") or local_elem.text
                vaga_info['localizacao'] = titulo
                #print("localização adquirida")
            except:
                vaga_info['localizacao'] = "Não informado"
                print("Erro ao adquirir a localização. ")
            
            # Data de publicação
            try:
                data_elem = vaga_element.find_element(By.XPATH, ".//h3[starts-with(text(), 'Publicada ')]")
                data_texto = data_elem.text
                vaga_info['data_publicacao'] = self.processar_data(data_texto)

            except:
                vaga_info['data_publicacao'] = datetime.now().date()
                print("Erro ao adquirir a data. ")
            
            return vaga_info
            
        except Exception as e:
            print(f"  ⚠️ Erro ao processar vaga da listagem: {e}")
            return None

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

    
    def acessar_detalhes_vaga(self, url_vaga):
        """Acessa a página de detalhes de uma vaga"""
        try:
            print(f"  🔍 Acessando: {url_vaga}")
            
            # Abre a vaga em uma nova aba
            self.driver.execute_script("window.open('');")
            self.driver.switch_to.window(self.driver.window_handles[-1])
            
            self.driver.get(url_vaga)
            time.sleep(random.uniform(2, 4))
            
            detalhes = {}
            
            # Aguarda a página carregar
            self.aguardar_elemento((By.TAG_NAME, "body"), timeout=10)
            
            # Pega todo o texto da página
            try:
                descricao_texto = self.driver.find_element(By.XPATH, ".//div[contains(@class, 'text-cinza90') and contains(@class, 'break-words')]").text
                detalhes['descricao'] = self.limpar_texto(descricao_texto)[:5000]  # Limita a 5000 caracteres
            except:
                detalhes['descricao'] = "Não informado"
                print("Erro ao extrair descrição")

            
            # Extrai informações do texto completo
            texto_completo = detalhes['descricao']
            
            # Modalidade
            try:
                modalidade = self.driver.find_element(By.XPATH, ".//p[normalize-space(text())='Tipo de vaga']/following-sibling::h3").text
                detalhes['modalidade'] = self.extrair_modalidade(modalidade)
            except:
                detalhes['modalidade'] = "Não informado"
                print("Erro ao extrair modalidade")
            
            # Salário
            try:
                salario = self.driver.find_element(By.XPATH, ".//p[normalize-space(text())='Remuneração']/following-sibling::h3").text
                detalhes['salario'] = self.extrair_salario(salario)
            except:
                detalhes['salario'] = "Não informado"
                print("Erro ao extrair salario")
            
            # Requisitos
            try:
                detalhes['requisitos'] = self.extrair_requisitos(texto_completo)
            except:
                detalhes['requisitos'] = "Não informado"
                print("Erro ao extrair requisitos")
            
            # Benefícios
            try:
                detalhes['beneficios'] = self.extrair_beneficios(texto_completo)
            except:
                detalhes['beneficios'] = "Não informado"
                print("Erro ao extrair beneficios")
            
            # Tipo de contrato
            try:
                detalhes['tipo_contrato'] = self.extrair_tipo_contrato(texto_completo)
            except:
                detalhes['tipo_contrato'] = "Não informado"
                print("Erro ao extrair tipo de contrato")
            
            # Fecha a aba e volta para a principal
            self.driver.close()
            self.driver.switch_to.window(self.driver.window_handles[0])
            
            return detalhes
            
        except Exception as e:
            print(f"  ❌ Erro ao acessar detalhes: {e}")
            
            # Tenta voltar para a aba principal
            try:
                if len(self.driver.window_handles) > 1:
                    self.driver.close()
                self.driver.switch_to.window(self.driver.window_handles[0])
            except:
                pass
            
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
    
    def coletar_vagas(self, url, max_paginas=3):
        """Coleta vagas do site empregos.com.br"""
        todas_vagas = []
        
        try:
            print(f"\n🌐 Acessando: {url}")
            self.driver.get(url)
            time.sleep(random.uniform(3, 5))
            
            # Aceita cookies se necessário
            try:
                cookie_btn = self.driver.find_element(By.XPATH, "//button[contains(text(), 'Aceitar') or contains(text(), 'OK')]")
                cookie_btn.click()
                time.sleep(1)
            except:
                pass
            
            for pagina in range(1, max_paginas + 1):
                print(f"\n📄 Processando página {pagina}...")
                
                # Aguarda as vagas carregarem
                vagas_elements = self.wait.until(
                    EC.presence_of_all_elements_located((By.XPATH, "//div[contains(@id, 'job-card')]" ))
                )
                
                print(f"📋 Encontradas {len(vagas_elements)} vagas na página {pagina}")


                # Processa cada vaga da página
                for i, vaga_elem in enumerate(vagas_elements, 1):
                    try:
                        print(f"  📝 Processando vaga {i}/{len(vagas_elements)}")
                        
                        # Scroll até a vaga
                        self.scroll_para_elemento(vaga_elem)
                        
                        # Extrai informações básicas da listagem
                        vaga_info = self.processar_vaga_listagem(vaga_elem)
                        
                        if vaga_info and vaga_info.get('url_vaga'):
                            # Acessa detalhes da vaga
                            detalhes = self.acessar_detalhes_vaga(vaga_info['url_vaga'])
                            
                            # Monta o objeto da vaga
                            vaga_completa = {
                                'titulo_vaga': vaga_info.get('titulo_vaga', 'Não informado'),
                                'empresa': vaga_info.get('empresa', 'Não informado'),
                                'localizacao': vaga_info.get('localizacao', 'Não informado'),
                                'salario': detalhes.get('salario', 'Não informado'),
                                'descricao': detalhes.get('descricao', vaga_info.get('descricao_breve', 'Não informado')),
                                'requisitos': detalhes.get('requisitos', 'Não informado'),
                                'beneficios': detalhes.get('beneficios', 'Não informado'),
                                'tipo_contrato': detalhes.get('tipo_contrato', 'Não informado'),
                                'modalidade': detalhes.get('modalidade', 'Não informado'),
                                'data_publicacao': vaga_info.get('data_publicacao', 'Não informado'),
                                'url_vaga': vaga_info.get('url_vaga', 'Não informado'),
                                'fonte': 'Empregos.com.br'
                            }
                            
                            # for campo in vaga_completa:
                            #     print(f"{campo}: {vaga_completa[campo]}")

                            todas_vagas.append(vaga_completa)
                            print(f"  ✅ Vaga coletada: {vaga_completa['titulo_vaga']} - {vaga_completa['empresa']}")
                            self.salvar_checkpoint_jsonl(vaga_completa)
                            print(f"  ✅ Vaga salva no JSON")

                            # Delay entre vagas
                            time.sleep(random.uniform(1, 3))
                            
                    except Exception as e:
                        print(f"  ⚠️ Erro ao processar vaga {i}: {e}")
                        continue
                
                # Tenta ir para próxima página
                if pagina < max_paginas:
                    try:
                        numero_proxima = str(pagina + 1)
                        next_btn = self.driver.find_element(
                            By.XPATH,
                            f"//a[normalize-space(text())='{numero_proxima}']"
                        )

                        self.scroll_para_elemento(next_btn)
                        time.sleep(1)

                        if next_btn.is_enabled():
                            self.clicar_com_javascript(next_btn)
                            time.sleep(random.uniform(3, 5))
                        else:
                            print("  ⚠️ Não há mais páginas disponíveis")
                            break
                            
                    except NoSuchElementException:
                        print("  ⚠️ Botão de próxima página não encontrado")
                        break
                    except Exception as e:
                        print(f"  ⚠️ Erro ao navegar para próxima página: {e}")
                        break
            
        except Exception as e:
            print(f"❌ Erro geral na coleta: {e}")
        
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
            "programador", "desenvolvedor", "TI", "tecnologia", "it", "IT", "ti", 
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