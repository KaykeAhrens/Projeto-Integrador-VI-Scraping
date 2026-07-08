import time
import random
import re
import os 
from datetime import datetime, timedelta, date
import psycopg2
import traceback
import base64
import json
from pathlib import Path

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    StaleElementReferenceException,
    WebDriverException
)
import undetected_chromedriver as uc
from groq import Groq
from urllib.parse import (
    urlsplit,
    urlunsplit,
    urljoin,
    quote,
    unquote,
    urlparse,
    quote_plus
)

CONNECTION_STRING = os.getenv("SUPABASE_CONNECTION_STRING")

CHECKPOINT_ARQ = Path("vagas_empregos3.jsonl")


class EmpregosComBrScraper:
    def __init__(self, headless=False):
        """Inicializa o scraper com Selenium"""
        self.driver = None
        self.wait = None
        self.setup_driver(headless)
        
    def setup_driver(self, headless=False):
        """Configura o driver com undetected-chromedriver, usando apenas as opções necessárias."""
        
        chrome_options = uc.ChromeOptions()
        
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--no-sandbox")
        
        chrome_options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')
        
        if headless:
            print("⚠️ Executando em modo headless. Se ocorrerem erros, tente em modo visual (headless=False).")
            chrome_options.add_argument('--headless=new')
        
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument('--start-maximized')
        
        try:
            print("🚀 Usando undetected-chromedriver com opções limpas...")
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
        if not CONNECTION_STRING:
            print("❌ Erro: Variável de ambiente 'SUPABASE_CONNECTION_STRING' não configurada.")
            return None

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
            f.write("") 

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
        Retorna True se a vaga for de TI (usando Groq), senão False.
        Usa fallback para heurística se API falhar ou não estiver configurada.
        """
        try:
            # Pegando a chave via variável de ambiente
            api_key = os.getenv('GROQ_API_KEY')
            if not api_key:
                print("      ⚠️ GROQ_API_KEY não configurada. Usando fallback heurístico.")
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

            payload = {k: v for k, v in vaga.items() if k in [
                "titulo_vaga", "descricao", "requisitos", "beneficios", "empresa",
                "localizacao", "tipo_contrato", "modalidade"
            ] and v and v != "Não informado"} # Envia apenas campos relevantes e preenchidos

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
                    is_ti_result = bool(data.get("is_ti", False))
                    print(f"      🤖 Groq classificou como TI: {is_ti_result}")
                    return is_ti_result
                except Exception as e:
                    print(f"      ⚠️ Groq erro (tentativa {attempt}/{max_retries}): {type(e).__name__} - {e}. ")
                    if attempt < max_retries:
                         wait_time = 1.5 * attempt
                         print(f"         Aguardando {wait_time:.1f}s antes de tentar novamente...")
                         time.sleep(wait_time)
                    else:
                         # Se todas as tentativas falharem, ativa o fallback
                         print(f"      ❌ Groq falhou após {max_retries} tentativas. USANDO FALLBACK HEURÍSTICO.")
                         return self._heuristica_is_ti(vaga) 

        except Exception as e_groq_setup:
            # Erro ao instanciar cliente Groq ou preparar a chamada
            print(f"      ❌ Falha inesperada no setup do classificador Groq: {e_groq_setup}. USANDO FALLBACK HEURÍSTICO.")
            return self._heuristica_is_ti(vaga) 

    def _heuristica_is_ti(self, vaga: dict) -> bool:
        """
        Classifica a vaga como TI ou não usando um sistema de pontuação
        baseado em palavras-chave positivas e negativas, com peso maior para o título.
        """
        # --- DEFINIÇÃO DAS PALAVRAS-CHAVE E PONTUAÇÕES ---

        # Palavras fortemente indicativas de TI (pontuação alta)
        # Usar \b para garantir palavras inteiras onde aplicável
        TI_KEYWORDS_STRONG = {
            # Cargos Core
            r'\bdev(s)?\b', 'developer', 'desenvolvedor(a)?', 'programador(a)?', 'software engineer', 'engenheiro de software',
            'arquiteto de software', 'software architect', 'front-end', 'frontend', 'back-end', 'backend', 'fullstack', 'full stack',
            'mobile developer', 'desenvolvedor mobile', 'data scientist', 'cientista de dados', 'machine learning', r'\bml\b',
            'engenheiro de dados', 'data engineer', 'devops', 'sre', 'site reliability', 'cloud engineer', 'engenheiro cloud',
            'security engineer', 'engenheiro de seguranca', 'cybersecurity', 'seguranca da informacao',
            'dba', 'database administrator', 'administrador de banco', 'network engineer', 'engenheiro de redes',
            'qa engineer', 'analista de testes', 'analista de qa', 'quality assurance', 'test automation', 'automacao de testes',
            'analista de sistemas', # Pode ser ambíguo, mas geralmente mais técnico
            r'\bcto\b', 'head of technology', 'tech lead',
            # Tecnologias Core
            'python', 'java', r'\bc#\b', r'\b\.net\b', 'javascript', 'typescript', 'php', 'ruby', 'golang', r'\bgo\b', 'swift', 'kotlin', r'\bc\+\+\b', r'\bc\b',
            'react', 'angular', 'vue', r'node\.?js', 'springboot', 'spring boot', 'django', 'flask', 'laravel', 'rails',
            'linux', 'unix', 'kernel', 'bash', 'powershell',
            'docker', 'kubernetes', r'\bk8s\b', 'container', 'terraform', 'ansible', 'jenkins', 'gitlab ci', 'github actions',
            r'\baws\b', 'azure', r'\bgcp\b', 'google cloud', 'oracle cloud', r'\boci\b', 'cloud computing', 'nuvem',
            'sql', 'database', 'banco de dados', 'postgres', 'mysql', 'sql server', 'oracle db', 'mongodb', 'nosql', 'cassandra', 'redis', 'elasticsearch',
            'api', r'\bapis\b', 'restful', 'graphql', 'microservices', 'microsservicos',
            'git', 'version control', 'ci/cd', 'integracao continua', 'entrega continua',
            'pentest', 'vulnerability', 'firewall', 'siem', 'cryptography', 'criptografia',
            'hadoop', 'spark', 'kafka', 'big data', 'data warehouse', r'\bdw\b', 'etl', 'data pipeline',
            'inteligencia artificial', r'\bia\b', 'artificial intelligence', r'\bai\b', 'deep learning', 'computer vision', r'\bnlp\b',
            'agile', 'scrum', 'kanban' # Metodologias comuns em TI
        }

        # Palavras medianamente indicativas de TI (pontuação menor)
        TI_KEYWORDS_MEDIUM = {
            'tech', 'technology', 'tecnologia', r'\bti\b', r'\b\.i\.t\b', 'informática', 'computação', 'computer science',
            'analytics', 'analise de dados', 'business intelligence', r'\bbi\b', 'data visualization', 'powerbi', 'tableau', 'qlik', 'metabase',
            'suporte técnico', 'technical support', 'helpdesk', 'service desk', # Cuidado: pode ser não-TI
            'product owner', r'\bpo\b', 'product manager', 'gerente de produto', # Foco em produto de software?
            'scrum master', 'agile coach',
            'ux designer', 'ui designer', 'designer de interface', 'designer de experiencia', 'figma', 'sketch', 'adobe xd',
            'redes', 'network', 'infraestrutura', 'infrastructure', 'servidores', 'servers', 'system administrator', 'administrador de sistemas',
            'erp', 'sap', 'totvs', 'protheus', 'crm', 'salesforce', # Sistemas específicos
            'html', 'css', 'web developer', 'web design', # Menos "core" que JS frameworks
            'hardware', # Montagem/Manutenção pode ser TI
            'dados', 'informações', # Contexto importa
            'automação', 'automation', # Pode ser industrial
            'consultor(a)? ti', 'it consultant'
        }

        # Palavras fortemente indicativas de NÃO ser TI (pontuação negativa alta)
        NON_IT_KEYWORDS = {
            # Cargos Claramente Não-TI
            'medico', 'enfermagem', 'enfermeiro', 'fisioterapeuta', 'nutricionista', 'farmaceutico', 'psicologo', 'veterinario',
            'advogado', 'jurídico', 'direito', 'legal',
            'contador', 'contabil', 'financeiro', 'finanças', 'tesouraria', 'auditor', 'atuario',
            'vendedor', 'representante comercial', 'gerente de vendas', 'consultor de vendas', 'atendente', 'caixa', 'balconista',
            'marketing', 'publicidade', 'propaganda', 'social media', 'conteudo', 'seo', # Exceto se muito técnico (ex: MarTech)
            'rh', 'recursos humanos', 'recrutador', 'departamento pessoal', 'dp', # Exceto se for "Tech Recruiter" especificamente
            'professor', 'instrutor', 'educador', 'pedagogo', # Exceto se for de TI
            'engenheiro civil', 'engenheiro mecanico', 'engenheiro eletricista', 'engenheiro quimico', 'engenheiro de producao', # Engenharia não-software
            'arquiteto (predial)', 'urbanista',
            'motorista', 'entregador', 'motoboy',
            'cozinheiro', 'garçom', 'barista', 'padeiro', 'açougueiro',
            'recepcionista', 'secretaria', 'assistente administrativo', # Geralmente não-TI
            'operador de maquina', 'operador de producao', 'auxiliar de producao', 'estoquista', 'logística', 'almoxarife',
            'zelador', 'porteiro', 'segurança', 'vigilante', 'limpeza', 'servicos gerais',
            'artista', 'musico', 'ator', 'atriz', 'modelo',
            'jornalista', 'reporter', 'radialista',
            'biologo', 'quimico', 'geologo',
            # Áreas/Termos Claramente Não-TI
            'construção civil', 'obras',
            'varejo', 'loja', 'comercio',
            'industrial', 'fabrica', 'manufatura', 'pcp', # Planejamento e Controle da Produção
            'agronomia', 'agropecuaria', 'zootecnia',
            'hotelaria', 'turismo'
        }

        # Código de heurística omitido para brevidade...
        # Retorno padrão para fechar o método, ajuste conforme sua regra de negócio
        return False
