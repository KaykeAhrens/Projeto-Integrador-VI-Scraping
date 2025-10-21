import time
import random
import re
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

CONNECTION_STRING = "postgresql://postgres.wnhqaiogzvvwrxcgfwsj:abkm@aws-1-sa-east-1.pooler.supabase.com:5432/postgres"

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
            api_key = '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'
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
            'hotelaria', 'turismo', 'restaurante', 'bar',
            'clinica', 'hospital', 'laboratorio', 'saude',
            'escola', 'faculdade', 'universidade', 'educacao',
            'escritorio de advocacia', 'forum',
            'banco (agencia)', # A menos que seja a área de TI do banco
            'imobiliaria', 'corretor de imoveis',
            'call center (atendimento geral)', 'telemarketing'
         }

        # Pontuações
        TITLE_STRONG_SCORE = 5
        TITLE_MEDIUM_SCORE = 3
        TEXT_STRONG_SCORE = 2
        TEXT_MEDIUM_SCORE = 1
        TEXT_NEGATIVE_SCORE = -4 # Pontuação negativa forte para evitar falsos positivos
        SCORE_THRESHOLD = 3 # Limite mínimo para ser considerado TI

        # --- CÁLCULO DA PONTUAÇÃO ---
        score = 0
        text_to_analyze = " ".join([
            vaga.get("titulo_vaga") or "",
            vaga.get("descricao") or "",
            vaga.get("requisitos") or "" # Benefícios geralmente não ajudam tanto na classificação
        ]).lower()
        title = (vaga.get("titulo_vaga") or "").lower()

        found_strong_positive = False
        found_negative = False

        # 1. Verifica Título
        for keyword in TI_KEYWORDS_STRONG:
            if re.search(r'\b' + keyword + r'\b', title):
                score += TITLE_STRONG_SCORE
                found_strong_positive = True
                print(f"      + Título match forte: '{keyword}' (+{TITLE_STRONG_SCORE})")
                break # Para no primeiro forte encontrado no título
        if not found_strong_positive: # Só checa médio no título se não achou forte
             for keyword in TI_KEYWORDS_MEDIUM:
                 if re.search(r'\b' + keyword + r'\b', title):
                     score += TITLE_MEDIUM_SCORE
                     print(f"      + Título match médio: '{keyword}' (+{TITLE_MEDIUM_SCORE})")
                     # Não quebra aqui, pode ter mais de um médio

        # 2. Verifica Texto Completo (Descrição + Requisitos)
        matched_strong = set()
        for keyword in TI_KEYWORDS_STRONG:
             # Usa re.search para \b funcionar corretamente
             if re.search(r'\b' + keyword + r'\b', text_to_analyze) and keyword not in matched_strong:
                 score += TEXT_STRONG_SCORE
                 found_strong_positive = True
                 print(f"      + Texto match forte: '{keyword}' (+{TEXT_STRONG_SCORE})")
                 matched_strong.add(keyword) # Conta cada keyword forte apenas uma vez

        matched_medium = set()
        for keyword in TI_KEYWORDS_MEDIUM:
             if re.search(r'\b' + keyword + r'\b', text_to_analyze) and keyword not in matched_medium:
                 score += TEXT_MEDIUM_SCORE
                 print(f"      + Texto match médio: '{keyword}' (+{TEXT_MEDIUM_SCORE})")
                 matched_medium.add(keyword) # Conta cada keyword média apenas uma vez

        matched_negative = set()
        for keyword in NON_IT_KEYWORDS:
             if re.search(r'\b' + keyword + r'\b', text_to_analyze) and keyword not in matched_negative:
                 score += TEXT_NEGATIVE_SCORE
                 found_negative = True
                 print(f"      - Texto match negativo: '{keyword}' ({TEXT_NEGATIVE_SCORE})")
                 matched_negative.add(keyword) # Conta cada keyword negativa apenas uma vez

        # --- DECISÃO FINAL ---
        is_ti_heuristic = score >= SCORE_THRESHOLD
        print(f"      🧠 Pontuação Final Heurística: {score} (Limite: {SCORE_THRESHOLD}) -> É TI? {is_ti_heuristic}")

        # Regra adicional: Se encontrou palavra negativa forte E NENHUMA positiva forte, provavelmente não é TI.
        if found_negative and not found_strong_positive and score < (SCORE_THRESHOLD + abs(TEXT_NEGATIVE_SCORE)):
             print(f"      -> Ajuste: Encontrado termo negativo sem termo positivo forte. Reclassificando para NÃO TI.")
             is_ti_heuristic = False


        return is_ti_heuristic
        
    def processar_vaga_listagem_simples(self, card_element):
        """
        Tenta extrair informações básicas e a URL da vaga de forma direta
        a partir do HTML do card, sem depender de cliques ou JS complexo.
        Prioriza encontrar um link direto ou ID.
        """
        vaga_info = {
            'titulo_vaga': "Não informado",
            'empresa': "Não informado",
            'localizacao': "Não informado",
            'data_publicacao': datetime.now().date(), # Fallback para data atual
            'url_vaga': None # Começa como None
        }

        try:
            # --- Extrair Título ---
            try:
                titulo_elem = card_element.find_element(By.XPATH, ".//span[contains(@class, 'text-base') and contains(@class, 'text-cinza90')]")
                vaga_info['titulo_vaga'] = self.limpar_texto(titulo_elem.text)
            except NoSuchElementException:
                print("      ⚠️ Título não encontrado no card.")
            except Exception as e:
                 print(f"      Erro ao extrair título: {e}")

            # --- Extrair Empresa ---
            try:
                # Tenta primeiro o link específico da empresa
                empresa_elem = card_element.find_element(By.XPATH, ".//div[contains(@class, 'flex-col')]//a[contains(@href, '/empresa/')]")
                vaga_info['empresa'] = self.limpar_texto(empresa_elem.text)
            except NoSuchElementException:
                # Fallback se não achar o link, tenta texto confidencial ou similar
                try:
                    empresa_elem = card_element.find_element(By.XPATH, ".//div[contains(@class, 'flex-col')]/h3")
                    vaga_info['empresa'] = self.limpar_texto(empresa_elem.text) # Pode ser "Confidencial"
                except NoSuchElementException:
                     print("      ⚠️ Empresa não encontrada no card.")
                except Exception as e:
                     print(f"      Erro ao extrair empresa (fallback): {e}")
            except Exception as e:
                 print(f"      Erro ao extrair empresa (link): {e}")


            # --- Extrair Localização ---
            try:
                # Prioriza o h3 com title, depois o texto do h3
                local_elems = card_element.find_elements(By.XPATH, ".//h3[@title]")
                if local_elems:
                    # Pega o primeiro h3 com title encontrado (geralmente é a localização)
                    loc_text = local_elems[0].get_attribute("title") or local_elems[0].text
                    vaga_info['localizacao'] = self.limpar_texto(loc_text)
                else:
                    # Fallback: Tenta achar h3 perto do ícone de localização
                    loc_elem = card_element.find_element(By.XPATH, ".//span[contains(@class, 'i-material-symbols:location-on-outline')]/following-sibling::h3")
                    vaga_info['localizacao'] = self.limpar_texto(loc_elem.text)
            except NoSuchElementException:
                print("      ⚠️ Localização não encontrada no card.")
            except Exception as e:
                print(f"      Erro ao extrair localização: {e}")

            # --- Extrair Data ---
            try:
                data_elem = card_element.find_element(By.XPATH, ".//h3[contains(text(), 'Publicada ')] | .//span[contains(text(), 'Publicada ')]/following-sibling::h3") # Tenta h3 ou span+h3
                data_texto = self.limpar_texto(data_elem.text)
                vaga_info['data_publicacao'] = self.processar_data(data_texto) # Usa sua função existente
            except NoSuchElementException:
                 print("      ⚠️ Data não encontrada no card.")
            except Exception as e:
                print(f"      Erro ao extrair data: {e}")

            url_encontrada = None

            # 1. Tentar link direto com /vaga/ DENTRO do card
            try:
                links_vaga = card_element.find_elements(By.XPATH, ".//a[contains(@href, '/vaga/')]")
                if links_vaga:
                    # Prioriza links que NÃO são da empresa e contêm um ID numérico razoável
                    for link in links_vaga:
                        href = link.get_attribute('href')
                        if href and '/empresa/' not in href and re.search(r'/vaga/\d{5,}/', href):
                             url_encontrada = href
                             print(f"      URL encontrada via link direto: {url_encontrada}")
                             break # Usa a primeira URL válida encontrada
                    if not url_encontrada and links_vaga: # Se só achou links de empresa ou sem ID claro
                        url_encontrada = links_vaga[0].get_attribute('href') # Pega o primeiro como fallback
                        print(f"      URL encontrada via link direto (fallback): {url_encontrada}")

            except Exception as e:
                print(f"      Erro ao buscar link direto /vaga/: {e}")


            # 2. Se não achou link direto, tentar link de candidatura (botão "Me candidatar")
            if not url_encontrada:
                try:
                    link_candidatar = card_element.find_element(By.XPATH, ".//a[contains(@href, 'formulario-curriculo?')]")
                    url_bruta_candidatar = link_candidatar.get_attribute('href')
                    match_id = re.search(r'vg=(\d{5,})', url_bruta_candidatar) 
                    if match_id:
                        id_vaga = match_id.group(1)
                        slug_titulo = re.sub(r'\W+', '-', vaga_info['titulo_vaga'].lower()).strip('-')
                        url_construida = f"/vaga/{id_vaga}/{slug_titulo}" 
                        url_encontrada = urljoin(self.BASE, url_construida)
                        print(f"      URL CONSTRUÍDA via ID ({id_vaga}) do botão 'Candidatar': {url_encontrada}")
                    else:
                         print("      Link 'Candidatar' encontrado, mas sem ID 'vg' válido.")

                except NoSuchElementException:
                    pass 
                except Exception as e:
                    print(f"      Erro ao buscar/processar link 'Candidatar': {e}")

            
            if not url_encontrada:
                try:
                    data_url = card_element.get_attribute('data-href') or card_element.get_attribute('data-url')
                    if data_url and '/vaga/' in data_url and re.search(r'\d{5,}', data_url): # Verifica se parece URL de vaga
                        url_encontrada = urljoin(self.BASE, data_url) # Torna absoluta se necessário
                        print(f"      URL encontrada via atributo data-* no card: {url_encontrada}")
                except Exception as e:
                    print(f"      Erro ao buscar atributo data-* no card: {e}")

            # 4. Tentar atributos data-href ou data-url no elemento PAI do card
            if not url_encontrada:
                try:
                    parent = card_element.find_element(By.XPATH, "..")
                    data_url_parent = parent.get_attribute('data-href') or parent.get_attribute('data-url')
                    if data_url_parent and '/vaga/' in data_url_parent and re.search(r'\d{5,}', data_url_parent):
                        url_encontrada = urljoin(self.BASE, data_url_parent)
                        print(f"      URL encontrada via atributo data-* no PAI: {url_encontrada}")
                except NoSuchElementException:
                    pass # Pode não ter pai ou o pai não ter o atributo
                except Exception as e:
                    print(f"      Erro ao buscar atributo data-* no PAI: {e}")

            # --- Finaliza e Normaliza ---
            if url_encontrada:
                vaga_info['url_vaga'] = self._normalize_url(url_encontrada)
            else:
                 print("      ⚠️ Nenhuma URL de vaga encontrada para este card pelas estratégias diretas.")
                 vaga_info['url_vaga'] = None

            return vaga_info

        except Exception as e_geral:
            print(f"      ❌ Erro GERAL em processar_vaga_listagem_simples: {type(e_geral).__name__} - {e_geral}")
            # traceback.print_exc() # Descomentar para debug
            vaga_info['url_vaga'] = None # Garante que retorna None em caso de erro
            return vaga_info

    # ================================================================
    #           FUNÇÃO coletar_vagas  (Estratégia 2 Fases)
    # ================================================================
    def coletar_vagas(self, url, max_paginas=3):
        """
        Coleta vagas usando a estratégia de 2 fases e classifica com Groq/Heurística.
        """
        urls_e_infos_basicas = [] # Lista para guardar o que coletar na Fase 1
        todas_vagas_completas_filtradas = [] # Lista final SÓ COM VAGAS DE TI

        try:
            print(f"\n🌐 [FASE 1] Iniciando coleta de URLs e infos básicas...")
            print(f"   Acessando URL inicial: {url}")
            self.driver.get(url)
            time.sleep(random.uniform(3, 5))

            # --- Aceitar Cookies ---
            try:
                cookie_button = WebDriverWait(self.driver, 7).until(EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Aceitar')]")))
                self.clicar_com_javascript(cookie_button)
                print("🍪 Cookies aceitos.")
                time.sleep(random.uniform(1, 2))
            except TimeoutException: print("ℹ️ Banner de cookies não encontrado ou já aceito.")
            except Exception as e_cookie: print(f"⚠️ Erro ao tentar aceitar cookies: {e_cookie}")

            # --- Loop pelas Páginas para Coletar URLs (FASE 1) ---
            for pagina_atual in range(1, max_paginas + 1):
                print("=" * 60)
                print(f"📄 [FASE 1] Coletando URLs da página Nº {pagina_atual}...")
                current_list_url = self.driver.current_url
                print(f"   URL da lista atual: {current_list_url}")

                try:
                    # Espera pelos cards
                    print("   ⏳ Aguardando cards da página carregarem...")
                    WebDriverWait(self.driver, 35).until(EC.presence_of_all_elements_located((By.XPATH, "//div[contains(@id, 'job-card')]")))
                    print("   ✅ Cards da página detectados.")
                    time.sleep(random.uniform(3, 5))

                    cards_na_pagina = self.driver.find_elements(By.XPATH, "//div[contains(@id, 'job-card')]")
                    num_cards = len(cards_na_pagina)
                    print(f"   🔎 Encontrados {num_cards} cards. Extraindo URLs/Infos básicas...")

                    if num_cards == 0:
                        print("   ⚠️ Nenhum card encontrado. Pulando para próxima página/keyword.")
                        continue

                    # Itera sobre os cards para extrair infos + URL
                    for i, card in enumerate(cards_na_pagina):
                        print(f"      Processando card {i + 1}/{num_cards}...")
                        try:
                            info_basica = self.processar_vaga_listagem_simples(card)
                            if info_basica and info_basica.get('url_vaga'):
                                urls_e_infos_basicas.append(info_basica)
                                print(f"         ✅ URL Coletada: {info_basica['url_vaga']}")
                                print(f"            Título: {info_basica.get('titulo_vaga', 'N/A')}")
                            else:
                                titulo_tentativo = info_basica.get('titulo_vaga', 'N/A') if info_basica else 'N/A'
                                print(f"         ⚠️ Falha ao extrair URL para o card {i + 1} ('{titulo_tentativo[:40]}...').")
                        except StaleElementReferenceException: print(f"      ❌ Card {i + 1} ficou 'stale'. Pulando.")
                        except Exception as e_extract: print(f"      ❌ Erro ao extrair info do card {i + 1}: {type(e_extract).__name__}")

                    # --- Fim do loop pelos cards, Tenta Paginar ---
                    if pagina_atual < max_paginas:
                        print("-" * 30); print(f"   ▶️ [FASE 1] Tentando ir para a página {pagina_atual + 1}...")
                        try:
                            # (Lógica de paginação - encontrar link/botão e clicar)
                            try: # Tenta link numérico primeiro
                                proxima_pagina_xpath = f"//div[contains(@class, 'pagination')]//a[normalize-space()='{pagina_atual + 1}' and not(contains(@class, 'active'))]"
                                proxima_pagina_link = WebDriverWait(self.driver, 15).until(EC.element_to_be_clickable((By.XPATH, proxima_pagina_xpath)))
                                print(f"      🖱️ Clicando link página {pagina_atual + 1}...")
                            except (NoSuchElementException, TimeoutException): # Fallback para botão "Próxima"
                                print(f"         Link numérico '{pagina_atual + 1}' não achado. Tentando 'Próxima'...")
                                proxima_pagina_xpath_fallback = "//a[contains(., 'Próxima') or @aria-label='Próxima página' or contains(@class, 'i-material-symbols:chevron-right-rounded')]/ancestor-or-self::a"
                                proxima_pagina_link = WebDriverWait(self.driver, 10).until(EC.element_to_be_clickable((By.XPATH, proxima_pagina_xpath_fallback)))
                                print(f"      🖱️ Clicando botão 'Próxima'...")

                            # Clica e espera carregar
                            self.scroll_para_elemento(proxima_pagina_link); time.sleep(0.5)
                            self.clicar_com_javascript(proxima_pagina_link)
                            nova_url_esperada_part = f"/{pagina_atual + 1}"
                            print(f"      ⏳ Aguardando paginação...")
                            WebDriverWait(self.driver, 35).until(EC.any_of(EC.url_contains(nova_url_esperada_part), EC.staleness_of(cards_na_pagina[0]) if cards_na_pagina else EC.url_contains(nova_url_esperada_part)))
                            print(f"      ✅ Paginação OK! URL: {self.driver.current_url}")
                            time.sleep(random.uniform(3, 5))
                        except (NoSuchElementException, TimeoutException): print("      ⏹️ Botão/Link de paginação não encontrado. Finalizando Fase 1."); break
                        except Exception as e_pag: print(f"      ❌ Erro na paginação: {e_pag}. Finalizando Fase 1."); break
                    else: print("   🏁 Máximo de páginas atingido."); break
                except Exception as e_page: print(f"   ❌ Erro processando página {pagina_atual}: {e_page}. Finalizando Fase 1."); break

            # --- FIM DA FASE 1 ---
            print("\n" + "=" * 60); print(f"🏁 [FASE 1] Coleta de URLs finalizada. Total: {len(urls_e_infos_basicas)}")

            # --- FASE 2: Processar Detalhes e Classificar ---
            print("\n" + "=" * 60); print(f"⚙️ [FASE 2] Iniciando processamento e classificação de {len(urls_e_infos_basicas)} vagas...")
            if not urls_e_infos_basicas: return []

            for idx, vaga_info in enumerate(urls_e_infos_basicas):
                print("-" * 30); print(f"   ➡️ [FASE 2] Vaga {idx + 1}/{len(urls_e_infos_basicas)}: {vaga_info.get('titulo_vaga', 'N/A')}")
                if not vaga_info.get('url_vaga'): print("      ⚠️ URL Inválida. Pulando."); continue

                # Acessa detalhes
                detalhes = self.acessar_detalhes_vaga(vaga_info['url_vaga'], expected_title=vaga_info.get('titulo_vaga'))

                if detalhes and detalhes.get('descricao') and detalhes.get('descricao') != "Não informado":
                    print(f"      ✅ Detalhes extraídos.")
                    vaga_completa = {**vaga_info, **detalhes, 'fonte': 'Empregos.com.br'}

                    # Limpeza final
                    for key, value in vaga_completa.items():
                        if isinstance(value, str):
                            cleaned = self.limpar_texto(value)
                            vaga_completa[key] = cleaned if cleaned else "Não informado"
                        elif value is None and key != 'data_publicacao': vaga_completa[key] = "Não informado"
                        if key == 'data_publicacao': # Converte data para ISO string
                             if isinstance(value, date): vaga_completa[key] = value.isoformat()
                             elif value is None: pass
                             elif not isinstance(value, str): vaga_completa[key] = datetime.now().date().isoformat()

                    # <<< CLASSIFICAÇÃO COM GROQ/FALLBACK >>>
                    print("      🤖 Classificando vaga com Groq (fallback para heurística)...")
                    is_ti = self._groq_is_ti(vaga_completa) # Chama a função que tem o fallback interno

                    if is_ti:
                        print("      ✅ Classificada como TI. Salvando...")
                        todas_vagas_completas_filtradas.append(vaga_completa) # Adiciona à lista final
                        self.salvar_checkpoint_jsonl(vaga_completa) # Salva no arquivo temporário
                        print(f"      💾 Vaga '{vaga_completa.get('titulo_vaga', 'N/A')}' salva no JSONL.")
                    else:
                        print(f"      ❌ Vaga '{vaga_completa.get('titulo_vaga', 'N/A')}' NÃO classificada como TI. Pulando salvamento.")

                else: print(f"      ❌ Falha ao obter detalhes para URL: {vaga_info.get('url_vaga')}")

                # Pausa entre acessos
                sleep_details = random.uniform(3.0, 6.0)
                print(f"      ⏳ Aguardando {sleep_details:.1f}s...")
                time.sleep(sleep_details)

        # --- Tratamento de Erros Gerais ---
        except KeyboardInterrupt: print("\n⏹️ Coleta interrompida.")
        except Exception as e_fatal: print(f"❌ Erro fatal: {e_fatal}"); traceback.print_exc()

        print(f"\n🏁 Coleta finalizada para URL base: {url}")
        print(f"   Total de vagas CLASSIFICADAS COMO TI e salvas no JSONL: {len(todas_vagas_completas_filtradas)}")
        return todas_vagas_completas_filtradas # Retorna APENAS as vagas de TI
    
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
                            
                            if cursor.rowcount == 1:
                                vagas_salvas += 1
                            else:
                                vagas_duplicadas += 1

                        conn.commit()
                        print(f"  ✅ Lote {i+1}-{i+len(lote)} salvo")
                        break  

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

        
    def verificar_estatisticas(self):
        """
        Verifica estatísticas do banco, abrindo e fechando a própria conexão.
        """
        conn = None 
        try:
            conn = self.get_conn() 
            if not conn:
                 print("❌ Não foi possível conectar ao banco para verificar estatísticas.")
                 return

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
            
            print(f"\n📊 ESTATÍSTICAS ATUAIS DO BANCO (Empregos.com.br):")
            print(f"   Total de vagas no banco: {total_empregos}")
            
            if modalidades:
                print(f"\n   Por modalidade no banco:")
                for modalidade, total in modalidades:
                    print(f"   • {modalidade}: {total}")
            
            cursor.close()
            
        except Exception as e:
            print(f"❌ Erro ao verificar estatísticas: {type(e).__name__} - {e}")
        finally:
            if conn:
                conn.close()
    
    
    def executar_com_keywords(self, keywords_selecionadas=None):
        """
        Executa o scraping usando keywords específicas E APLICANDO O FILTRO DE TI NA URL.
        As funções de DB gerenciam suas próprias conexões.
        """
        print("🚀 INICIANDO SCRAPING EMPREGOS.COM.BR COM KEYWORDS (FILTRO TI ATIVADO)")
        print("=" * 60)

        self.reset_checkpoint_jsonl()

        todas_keywords = [
            "desenvolvedor", "TI", "tecnologia", "it", "IT", "ti",
            "tecnologia da informação", "sistemas", "engenheiro de software",
            "dados", "inteligência de dados", "data", "python", "java",
            "javascript", "c++", "c#", "react", "angular", "node", "laravel",
            "django", "full stack", "backend", "frontend", "mobile",
            "data scientist", "cientista de dados", "analista de dados",
            "data analyst", "engenheiro de dados", "data engineer",
            "machine learning", "ml", "deep learning", "ai",
            "inteligência artificial", "big data", "analytics",
            "analista de sistemas", "business intelligence", "bi", "BI",
            "sql", "postgresql", "mysql", "mongodb", "nosql", "database",
            "dba", "data warehouse", "snowflake", "devops", "cloud", "aws",
            "azure", "gcp", "google cloud", "docker", "kubernetes"
        ]
        keywords = keywords_selecionadas if keywords_selecionadas else todas_keywords
        print(f"📋 Total de keywords para busca (com filtro TI): {len(keywords)}")


        try:
            self.verificar_estatisticas() 

            todas_vagas_coletadas_filtradas = [] 

            for idx, keyword in enumerate(keywords, 1):
                print(f"\n🔍 [{idx}/{len(keywords)}] Buscando: '{keyword}' (filtrado para TI)")

                # --- CONSTRUÇÃO DA URL COM FILTRO ---
                keyword_url_path = keyword.replace(" ", "-").lower()
                filter_payload = {
                    "keyword": [keyword],
                    "filters": [{"facetItem": 16, "description": "Informática/ Tecnologia"}],
                    "page": 0, "size": 20, "order": 0, "distance": 40
                }
                json_payload = json.dumps(filter_payload, separators=(',', ':'), ensure_ascii=False)
                base64_bytes = base64.b64encode(json_payload.encode('utf-8'))
                base64_string = base64_bytes.decode('utf-8')
                encoded_query_param = quote_plus(base64_string)
                url_filtrada = f"https://www.empregos.com.br/vagas/{keyword_url_path}/1?q={encoded_query_param}"
                print(f"   URL Filtrada: {url_filtrada}")
                print("-" * 40)
                # --- FIM DA CONSTRUÇÃO DA URL ---

                # Chama coletar_vagas (que já tem o filtro Groq interno)
                vagas_da_keyword = self.coletar_vagas(url_filtrada, max_paginas=2) 

                if vagas_da_keyword:
                    print(f"   ✅ {len(vagas_da_keyword)} vagas (filtradas internamente) encontradas para '{keyword}'")
                    todas_vagas_coletadas_filtradas.extend(vagas_da_keyword)
                else:
                    print(f"   ⚠️ Nenhuma vaga passou no filtro interno para '{keyword}'.")

                # Pausa entre keywords
                if idx < len(keywords):
                    tempo_espera = random.uniform(4, 8)
                    print(f"   ⏱️ Aguardando {tempo_espera:.1f}s antes da próxima busca...")
                    time.sleep(tempo_espera)

            print(f"\n📈 RESULTADO GERAL:")
            print(f"   Total de keywords processadas: {len(keywords)}")
            print(f"   Total de vagas de TI coletadas: {len(todas_vagas_coletadas_filtradas)}")

            if todas_vagas_coletadas_filtradas:
                print("\n📊 Distribuição das vagas de TI:")
                modalidades_count = {}
                contratos_count = {}
                for vaga in todas_vagas_coletadas_filtradas:
                    mod = vaga.get('modalidade', 'Não informado')
                    modalidades_count[mod] = modalidades_count.get(mod, 0) + 1
                    cont = vaga.get('tipo_contrato', 'Não informado')
                    contratos_count[cont] = contratos_count.get(cont, 0) + 1

                print("\n   Por Modalidade:")
                for modalidade, count in sorted(modalidades_count.items(), key=lambda x: x[1], reverse=True):
                    print(f"   • {modalidade}: {count}")
                print("\n   Por Tipo de Contrato:")
                for contrato, count in sorted(contratos_count.items(), key=lambda x: x[1], reverse=True):
                    print(f"   • {contrato}: {count}")
                
                # Salva no banco (esta função já abre sua própria conexão)
                print("\n💾 Salvando vagas de TI no banco de dados...")
                self.salvar_vagas_supabase(todas_vagas_coletadas_filtradas)

                # Mostra estatísticas finais (agora chama sem 'conn')
                self.verificar_estatisticas() 
            else:
                print("⚠️ Nenhuma vaga de TI foi coletada no total.")

        except KeyboardInterrupt:
            print("\n⏹️ Scraping interrompido pelo usuário")
        except Exception as e:
            print(f"\n❌ Erro durante execução: {e}")
            traceback.print_exc()
        finally:

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
    
    main()