import requests
from bs4 import BeautifulSoup
import psycopg2
from datetime import datetime
import time
import random
from urllib.parse import urljoin, urlparse, parse_qs, urlparse, parse_qs, urlencode, urlunparse
import re

# 🔴 COLE SUA CONNECTION STRING AQUI (substitua a linha abaixo)
CONNECTION_STRING = "postgresql://postgres.wnhqaiogzvvwrxcgfwsj:abkm@aws-1-sa-east-1.pooler.supabase.com:5432/postgres"

# Headers para simular um navegador real
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'pt-BR,pt;q=0.9,en;q=0.8',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1'
}

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
    
    # Remove quebras de linha excessivas e espaços
    texto = re.sub(r'\s+', ' ', texto.strip())
    # Remove caracteres especiais desnecessários
    texto = re.sub(r'[^\w\s\-\.,;:()R$%+/]', '', texto)
    
    return texto if texto else "Não informado"

def extrair_modalidade_da_url(url):
    """Extrai a modalidade de trabalho baseada nos parâmetros da URL"""
    try:
        parsed_url = urlparse(url)
        query_params = parse_qs(parsed_url.query)
        
        # Verifica se existe o parâmetro 'm[]' (modalidade)
        if 'm[]' in query_params:
            modalidade_param = query_params['m[]'][0]  # Pega o primeiro valor
            
            # Mapeia os valores dos parâmetros para modalidades
            modalidade_mapping = {
                'Na empresa': 'Presencial',
                'Empresa e Home Office': 'Híbrido',
                'Home Office': 'Remoto'
            }
            
            return modalidade_mapping.get(modalidade_param, modalidade_param)
    
    except Exception as e:
        print(f"⚠️  Erro ao extrair modalidade da URL: {e}")
    
    return None

def extrair_requisitos_inteligente(desc_text):
    """Extrai requisitos da descrição usando múltiplas estratégias"""
    if not desc_text:
        return "Não informado"
    
    desc_lower = desc_text.lower()
    requisitos_encontrados = []
    
    # ESTRATÉGIA 1: Busca por padrões comuns de requisitos (ampliados)
    patterns_requisitos = [
        # Padrões principais
        'requisitos:',
        'outros requisitos:',
        'requisitos necessários:',
        'requisitos obrigatórios:',
        'pré-requisitos:',
        'pré requisitos:',
        
        # Padrões de expectativas
        'esperamos que você tenha:',
        'esperamos que voce tenha:',
        'o que esperamos de você:',
        'o que esperamos de voce:',
        'você deve ter:',
        'voce deve ter:',
        'você precisa ter:',
        'voce precisa ter:',
        
        # Padrões de necessidades
        'necessário:',
        'necessario:',
        'é necessário:',
        'eh necessario:',
        'obrigatório:',
        'obrigatorio:',
        
        # Padrões de qualificações
        'qualificações:',
        'qualificacoes:',
        'qualificações necessárias:',
        'qualificacoes necessarias:',
        'qualificações desejadas:',
        'qualificacoes desejadas:',
        
        # Padrões de exigências
        'exigências:',
        'exigencias:',
        'exigimos:',
        
        # Padrões de competências
        'competências necessárias:',
        'competencias necessarias:',
        'habilidades necessárias:',
        'habilidades necessarias:',
        
        # Padrões de perfil
        'perfil desejado:',
        'perfil necessário:',
        'perfil necessario:',
        'perfil do candidato:',
    ]
    
    # Busca pelo melhor padrão encontrado
    melhor_match = None
    melhor_posicao = -1
    
    for pattern in patterns_requisitos:
        posicao = desc_lower.find(pattern)
        if posicao != -1:
            if melhor_posicao == -1 or posicao < melhor_posicao:
                melhor_match = pattern
                melhor_posicao = posicao
    
    if melhor_match and melhor_posicao != -1:
        start_idx = melhor_posicao
        
        # Padrões que indicam fim da seção de requisitos
        end_patterns = [
            'o que oferecemos',
            'oferecemos:',
            'benefícios',
            'beneficios',
            'será um diferencial',
            'sera um diferencial',
            'diferenciais:',
            'contratação',
            'contratacao',
            'salário',
            'salario',
            'localização',
            'localizacao',
            'modalidade',
            'jornada',
            'carga horária',
            'carga horaria',
            'informações adicionais',
            'informacoes adicionais',
            'sobre a empresa',
            'descrição da empresa',
            'descricao da empresa'
        ]
        
        # Procura o fim da seção
        end_idx = start_idx + 800  # Máximo de 800 caracteres
        
        for end_pattern in end_patterns:
            temp_end = desc_lower.find(end_pattern, start_idx + len(melhor_match))
            if temp_end != -1 and temp_end < end_idx:
                end_idx = temp_end
        
        requisitos_text = desc_text[start_idx:end_idx].strip()
        
        # Remove o padrão inicial para ficar só o conteúdo
        if requisitos_text.lower().startswith(melhor_match):
            requisitos_text = requisitos_text[len(melhor_match):].strip()
        
        if len(requisitos_text) > 20:  # Só considera se tiver conteúdo substancial
            requisitos_encontrados.append(requisitos_text)
    
    # ESTRATÉGIA 2: Se não encontrou pelos padrões, busca por seções estruturadas
    if not requisitos_encontrados:
        # Procura por listas de requisitos (linhas que começam com -, •, *, números)
        linhas = desc_text.split('\n')
        secao_requisitos = []
        capturando = False
        
        for i, linha in enumerate(linhas):
            linha_lower = linha.lower().strip()
            
            # Verifica se é uma linha que indica início de requisitos
            if any(pattern in linha_lower for pattern in ['requisito', 'necessário', 'obrigatório', 'graduação', 'formação', 'experiência']):
                capturando = True
                secao_requisitos.append(linha.strip())
            elif capturando:
                # Continua capturando se for item de lista ou linha relacionada
                if (linha.strip().startswith(('-', '•', '*')) or 
                    linha_lower.startswith(('conhecimento', 'experiência', 'dominio', 'habilidade')) or
                    re.match(r'^\d+[\.)]\s', linha.strip())):
                    secao_requisitos.append(linha.strip())
                elif len(linha.strip()) < 10:  # Linha muito curta, continua
                    continue
                else:
                    # Se chegou numa linha que não parece ser requisito, para
                    break
        
        if secao_requisitos:
            requisitos_text = '\n'.join(secao_requisitos)
            if len(requisitos_text) > 20:
                requisitos_encontrados.append(requisitos_text)
    
    # ESTRATÉGIA 3: Busca por palavras-chave de requisitos comuns
    if not requisitos_encontrados:
        keywords_requisitos = ['graduação', 'formação', 'superior', 'ensino médio', 'técnico', 
                              'experiência', 'anos de experiência', 'conhecimento', 'domínio']
        
        for keyword in keywords_requisitos:
            if keyword in desc_lower:
                # Encontra a frase que contém a palavra-chave
                sentences = re.split(r'[.;!?]\s+', desc_text)
                requisitos_sentences = []
                
                for sentence in sentences:
                    if keyword in sentence.lower():
                        requisitos_sentences.append(sentence.strip())
                
                if requisitos_sentences:
                    requisitos_text = '. '.join(requisitos_sentences[:3])  # Pega até 3 frases
                    if len(requisitos_text) > 20:
                        requisitos_encontrados.append(requisitos_text)
                        break
    
    # Retorna o melhor requisito encontrado
    if requisitos_encontrados:
        return limpar_texto(requisitos_encontrados[0])
    
    return "Não informado"

def extrair_detalhes_vaga(url_vaga, session, modalidade_url=None):
    """Extrai detalhes completos da vaga acessando a página individual usando seletores específicos"""
    try:
        print(f"  🔍 Acessando detalhes: {url_vaga}")
        
        response = session.get(url_vaga, headers=HEADERS, timeout=10)
        if response.status_code != 200:
            print(f"  ❌ Erro ao acessar detalhes: {response.status_code}")
            return {}
        
        soup = BeautifulSoup(response.content, 'html.parser')
        detalhes = {}
        
        # 1. INFORMAÇÕES DA DIV .infoVaga
        info_vaga = soup.find('div', class_='infoVaga')
        if info_vaga:
            # Salário - procura pelo ícone de salário
            salario_li = info_vaga.find('figure', class_='icone-salario')
            if salario_li:
                salario_parent = salario_li.parent
                salario_spans = salario_parent.find_all('span')
                if len(salario_spans) >= 2:
                    detalhes['salario'] = limpar_texto(salario_spans[1].get_text())
            
            # Localização - procura pelo ícone de localização (limpa, sem tooltip)
            loc_li = info_vaga.find('figure', class_='icone-localizacao')
            if loc_li:
                loc_span = info_vaga.find('span', class_='info-localizacao')
                if loc_span:
                    # Pega apenas o texto principal, sem tooltip
                    texto_loc = loc_span.get_text(separator=' ', strip=True)
                    # Remove qualquer menção de tooltip
                    if "A empresa aceita" in texto_loc:
                        texto_loc = texto_loc.split("A empresa aceita")[0].strip()
                    detalhes['localizacao'] = limpar_texto(texto_loc)
            
            # Tipo de contrato - procura pelo ícone de modelo de contratação
            contrato_li = info_vaga.find('figure', class_='icone-modelo-contratacao')
            if contrato_li:
                contrato_span = info_vaga.find('span', class_='info-modelo-contratual')
                if contrato_span:
                    detalhes['tipo_contrato'] = limpar_texto(contrato_span.get_text())
        
        # 2. BENEFÍCIOS - div.job-tab-content.job-benefits
        beneficios_div = soup.find('div', {'class': 'job-tab-content job-benefits', 'data-testid': 'JobBenefits'})
        if beneficios_div:
            beneficios_list = []
            benefit_items = beneficios_div.find_all('li', class_='job-benefits__list-item')
            for item in benefit_items:
                benefit_span = item.find('span', class_='benefit-label')
                if benefit_span:
                    beneficios_list.append(benefit_span.get_text().strip())
            
            if beneficios_list:
                detalhes['beneficios'] = '; '.join(beneficios_list)
        
        # 3. DESCRIÇÃO - div.job-tab-content.job-description__text
        desc_div = soup.find('div', {'class': 'job-tab-content job-description__text texto', 'data-testid': 'JobDescription'})
        if desc_div:
            # Remove tags HTML e limpa o texto
            desc_text = desc_div.get_text(separator=' ', strip=True)
            detalhes['descricao'] = limpar_texto(desc_text)
            
            # 4. EXTRAI REQUISITOS da descrição usando função melhorada
            requisitos = extrair_requisitos_inteligente(desc_text)
            detalhes['requisitos'] = requisitos
            
            if requisitos != "Não informado":
                print(f"  ✅ Requisitos encontrados: {requisitos[:100]}...")
            else:
                print(f"  ⚠️  Requisitos não encontrados na descrição")
        
        # 5. MODALIDADE - SEMPRE usa a modalidade da URL (não analisa mais descrição)
        if modalidade_url:
            detalhes['modalidade'] = modalidade_url
            print(f"  📍 Modalidade definida pela URL: {modalidade_url}")
        else:
            detalhes['modalidade'] = "Não informado"
            print(f"  ⚠️  Modalidade não informada na URL")
        
        time.sleep(1)  # Delay para não sobrecarregar o servidor
        return detalhes
        
    except Exception as e:
        print(f"  ❌ Erro ao extrair detalhes da vaga: {e}")
        return {}

def extrair_salario(texto_salario):
    """Extrai e formata informação de salário"""
    if not texto_salario:
        return "Não informado"
    
    texto = texto_salario.lower().strip()
    
    # Se contém "a combinar" ou similar
    if any(palavra in texto for palavra in ['combinar', 'negociar', 'negociável']):
        return "A combinar"
    
    # Se contém valores em R$
    if 'r$' in texto or 'reais' in texto:
        return limpar_texto(texto_salario)
    
    return "Não informado"

def fazer_scraping_vagas(url_base, max_carregamentos=5):
    """Faz o scraping das vagas do Vagas.com usando sistema de 'mostrar mais'"""
    
    session = requests.Session()
    session.headers.update(HEADERS)
    
    todas_vagas = []
    pagina_atual = 1
    
    # Extrai modalidade da URL base
    modalidade_url_base = extrair_modalidade_da_url(url_base)
    if modalidade_url_base:
        print(f"🎯 Modalidade detectada na URL: {modalidade_url_base}")
    
    print(f"\n📄 Carregando primeira página: {url_base}")
    
    # Carrega a primeira página
    try:
        response = session.get(url_base, headers=HEADERS, timeout=15)
        
        if response.status_code != 200:
            print(f"❌ Erro ao carregar página inicial: {response.status_code}")
            return []
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Processa vagas da primeira página
        vagas_elementos = soup.find_all('li', class_='vaga')
        
        if not vagas_elementos:
            print("⚠️  Nenhuma vaga encontrada na página inicial")
            return []
        
        print(f"📋 Encontradas {len(vagas_elementos)} vagas na página inicial")
        
        # Processa vagas da primeira página
        todas_vagas.extend(processar_vagas_pagina(vagas_elementos, session, pagina_atual, modalidade_url_base))
        
    except Exception as e:
        print(f"❌ Erro ao carregar página inicial: {e}")
        return []
    
    # Agora carrega as páginas adicionais usando o botão "mostrar mais"
    for carregamento in range(2, max_carregamentos + 1):
        try:
            # Encontra o botão "mostrar mais" e extrai a URL
            botao_mais = soup.find('a', class_='btMaisVagas') or soup.find('a', id='maisVagas')
            
            if not botao_mais or not botao_mais.get('data-url'):
                print(f"⚠️  Não encontrou botão 'mostrar mais'. Finalizando na página {carregamento-1}")
                break
            
            # Constrói URL da próxima página
            url_proxima = botao_mais['data-url']
            if url_proxima.startswith('/'):
                url_proxima = f"https://www.vagas.com.br{url_proxima}"
            
            # Verifica se a modalidade se mantém na nova URL
            modalidade_url_proxima = extrair_modalidade_da_url(url_proxima) or modalidade_url_base
            
            print(f"\n📄 Carregando página {carregamento}: {url_proxima}")
            
            # Faz requisição para próxima página
            response = session.get(url_proxima, headers=HEADERS, timeout=15)
            
            if response.status_code != 200:
                print(f"❌ Erro na página {carregamento}: {response.status_code}")
                break
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Encontra as vagas na nova página
            vagas_elementos = soup.find_all('li', class_='vaga')
            
            if not vagas_elementos:
                print(f"⚠️  Nenhuma vaga encontrada na página {carregamento}")
                break
            
            print(f"📋 Encontradas {len(vagas_elementos)} vagas na página {carregamento}")
            
            # Processa vagas desta página
            vagas_novas = processar_vagas_pagina(vagas_elementos, session, carregamento, modalidade_url_proxima)
            
            if not vagas_novas:
                print(f"⚠️  Nenhuma vaga nova processada na página {carregamento}")
                break
            
            todas_vagas.extend(vagas_novas)
            
            # Delay entre carregamentos
            print(f"⏱️  Aguardando antes do próximo carregamento...")
            time.sleep(random.uniform(3, 6))
            
        except Exception as e:
            print(f"❌ Erro no carregamento {carregamento}: {e}")
            continue
    
    return todas_vagas

def processar_vagas_pagina(vagas_elementos, session, numero_pagina, modalidade_url=None):
    """Processa as vagas de uma página específica"""
    vagas_processadas = []
    
    for i, vaga_elem in enumerate(vagas_elementos, 1):
        try:
            print(f"  📝 Processando vaga {i}/{len(vagas_elementos)} (página {numero_pagina})")
            
            # Título da vaga
            titulo_elem = vaga_elem.find('h2', class_='cargo')
            titulo = limpar_texto(titulo_elem.get_text()) if titulo_elem else "Não informado"
            
            # Empresa
            empresa_elem = vaga_elem.find('span', class_='emprVaga')
            empresa = limpar_texto(empresa_elem.get_text()) if empresa_elem else "Não informado"
            
            # Localização - usando div.vaga-local (sem tooltip)
            localizacao_elem = vaga_elem.find('div', class_='vaga-local')
            localizacao = "Não informado"
            if localizacao_elem:
                # Remove ícone e pega só texto limpo
                texto_loc = localizacao_elem.get_text(separator=' ', strip=True)
                # Remove qualquer texto do tooltip
                if "A empresa aceita" in texto_loc:
                    texto_loc = texto_loc.split("A empresa aceita")[0].strip()
                # Limpa texto final
                localizacao = limpar_texto(texto_loc)
            
            # Data de publicação - usando span.data-publicacao
            data_publicacao = datetime.now().date()  # default
            data_elem = vaga_elem.find('span', class_='data-publicacao')
            if data_elem:
                try:
                    # Extrai apenas a data, ignorando o ícone
                    data_texto = data_elem.get_text().strip()
                    # Remove ícone se existir (às vezes fica como caractere)
                    data_texto = re.sub(r'[^\d/]', '', data_texto)
                    if data_texto:
                        data_publicacao = datetime.strptime(data_texto, '%d/%m/%Y').date()
                except:
                    pass  # Mantém data atual se der erro
            
            # Nível da vaga (Júnior/Pleno/Sênior) - usando span.nivelVaga
            nivel_elem = vaga_elem.find('span', class_='nivelVaga')
            nivel_vaga = limpar_texto(nivel_elem.get_text()) if nivel_elem else "Não informado"
            
            # Link da vaga
            link_elem = vaga_elem.find('a', class_='link-detalhes-vaga')
            if link_elem and link_elem.get('href'):
                url_vaga = urljoin("https://www.vagas.com.br", link_elem['href'])
            else:
                url_vaga = "Não informado"
            
            # Descrição básica da listagem
            desc_elem = vaga_elem.find('div', class_='detalhes')
            descricao_basica = "Não informado"
            if desc_elem:
                # Pega só o primeiro parágrafo se existir
                p_elem = desc_elem.find('p')
                if p_elem:
                    descricao_basica = limpar_texto(p_elem.get_text())
                else:
                    descricao_basica = limpar_texto(desc_elem.get_text())
            
            # Extrai detalhes completos da página da vaga (passa a modalidade da URL)
            detalhes_extras = {}
            if url_vaga != "Não informado":
                detalhes_extras = extrair_detalhes_vaga(url_vaga, session, modalidade_url)
            
            # Cria o objeto da vaga
            vaga_data = {
                'titulo_vaga': titulo,
                'empresa': empresa,
                'localizacao': detalhes_extras.get('localizacao', localizacao),
                'salario': detalhes_extras.get('salario', 'Não informado'),
                'descricao': detalhes_extras.get('descricao', descricao_basica),
                'requisitos': detalhes_extras.get('requisitos', 'Não informado'),
                'beneficios': detalhes_extras.get('beneficios', 'Não informado'),
                'tipo_contrato': detalhes_extras.get('tipo_contrato', nivel_vaga),
                'modalidade': detalhes_extras.get('modalidade', modalidade_url or 'Não informado'),
                'data_publicacao': data_publicacao,
                'url_vaga': url_vaga,
                'fonte': 'Vagas.com'
            }
            
            vagas_processadas.append(vaga_data)
            print(f"  ✅ Vaga coletada: {titulo} - {empresa} ({localizacao}) - Modalidade: {vaga_data['modalidade']} - {data_publicacao}")
            
            # Delay entre vagas para não sobrecarregar
            time.sleep(random.uniform(0.5, 1.5))
            
        except Exception as e:
            print(f"  ❌ Erro ao processar vaga {i}: {e}")
            continue
    
    return vagas_processadas

def construir_urls_modalidades(url_base):
    """Constrói URLs com diferentes filtros de modalidade"""
    parsed_url = urlparse(url_base)
    query_params = parse_qs(parsed_url.query)
    
    # Remove qualquer modalidade existente
    if 'm[]' in query_params:
        del query_params['m[]']
    
    modalidades = {
        'Presencial': 'Na empresa',
        'Híbrido': 'Empresa e Home Office',
        'Remoto': 'Home Office'
    }
    
    urls_modalidades = {}
    
    for modalidade_nome, modalidade_param in modalidades.items():
        # Adiciona o parâmetro de modalidade
        new_params = query_params.copy()
        new_params['m[]'] = [modalidade_param]
        
        # Reconstrói a URL
        new_query = urlencode(new_params, doseq=True)
        new_url = urlunparse((
            parsed_url.scheme,
            parsed_url.netloc,
            parsed_url.path,
            parsed_url.params,
            new_query,
            parsed_url.fragment
        ))
        
        urls_modalidades[modalidade_nome] = new_url
    
    return urls_modalidades

def salvar_vagas_supabase(conn, vagas):
    """Salva as vagas coletadas no Supabase com tratamento de duplicatas"""
    
    if not vagas:
        print("⚠️  Nenhuma vaga para salvar")
        return
    
    try:
        cursor = conn.cursor()
        
        # SQL para inserir ignorando duplicatas (ON CONFLICT)
        sql_insert = """
        INSERT INTO vagas_emprego (
            titulo_vaga, empresa, localizacao, salario, descricao, 
            requisitos, beneficios, tipo_contrato, modalidade, 
            data_publicacao, url_vaga, fonte
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        ) ON CONFLICT (url_vaga) DO NOTHING;
        """
        
        # SQL para verificar se vaga já existe
        sql_check = "SELECT COUNT(*) FROM vagas_emprego WHERE url_vaga = %s;"
        
        vagas_salvas = 0
        vagas_duplicadas = 0
        vagas_erro = 0
        
        print(f"💾 Processando {len(vagas)} vagas...")
        
        for i, vaga in enumerate(vagas, 1):
            try:
                # Verifica se a vaga já existe
                cursor.execute(sql_check, (vaga['url_vaga'],))
                existe = cursor.fetchone()[0] > 0
                
                if existe:
                    vagas_duplicadas += 1
                    print(f"  🔄 ({i}/{len(vagas)}) Vaga já existe: {vaga['titulo_vaga']}")
                    continue
                
                # Insere a vaga
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
                
                # Verifica se realmente inseriu
                if cursor.rowcount > 0:
                    vagas_salvas += 1
                    print(f"  ✅ ({i}/{len(vagas)}) Nova vaga salva: {vaga['titulo_vaga']}")
                else:
                    vagas_duplicadas += 1
                    print(f"  🔄 ({i}/{len(vagas)}) Vaga duplicada ignorada: {vaga['titulo_vaga']}")
                
            except Exception as e:
                print(f"  ❌ ({i}/{len(vagas)}) Erro ao salvar '{vaga['titulo_vaga']}': {e}")
                vagas_erro += 1
                # Em caso de erro, faz rollback parcial e continua
                conn.rollback()
                continue
        
        # Commit final
        conn.commit()
        cursor.close()
        
        print(f"\n✅ RESULTADO DO SALVAMENTO:")
        print(f"   📊 Vagas novas salvas: {vagas_salvas}")
        print(f"   🔄 Vagas duplicadas ignoradas: {vagas_duplicadas}")
        if vagas_erro > 0:
            print(f"   ❌ Vagas com erro: {vagas_erro}")
        print(f"   📈 Total processadas: {len(vagas)}")
        
    except Exception as e:
        print(f"❌ Erro geral ao salvar no banco: {e}")
        conn.rollback()

def verificar_vagas_salvas(conn):
    """Verifica quantas vagas foram salvas no total"""
    try:
        cursor = conn.cursor()
        
        # Total geral
        cursor.execute("SELECT COUNT(*) FROM vagas_emprego;")
        total_geral = cursor.fetchone()[0]
        
        # Total do Vagas.com
        cursor.execute("SELECT COUNT(*) FROM vagas_emprego WHERE fonte = 'Vagas.com';")
        total_vagas_com = cursor.fetchone()[0]
        
        # Total por modalidade
        cursor.execute("""
            SELECT modalidade, COUNT(*) as total 
            FROM vagas_emprego 
            WHERE fonte = 'Vagas.com'
            GROUP BY modalidade
            ORDER BY total DESC;
        """)
        modalidades = cursor.fetchall()
        
        # Verifica duplicatas
        cursor.execute("""
            SELECT url_vaga, COUNT(*) as total 
            FROM vagas_emprego 
            WHERE fonte = 'Vagas.com' 
            GROUP BY url_vaga 
            HAVING COUNT(*) > 1
            ORDER BY total DESC;
        """)
        duplicatas = cursor.fetchall()
        
        # Últimas 5 vagas do Vagas.com
        cursor.execute("""
            SELECT titulo_vaga, empresa, localizacao, modalidade, data_coleta 
            FROM vagas_emprego 
            WHERE fonte = 'Vagas.com'
            ORDER BY data_coleta DESC 
            LIMIT 5;
        """)
        
        ultimas_vagas = cursor.fetchall()
        
        print(f"\n📊 ESTATÍSTICAS DO BANCO:")
        print(f"   Total de vagas (geral): {total_geral}")
        print(f"   Total do Vagas.com: {total_vagas_com}")
        
        if modalidades:
            print(f"\n📈 Vagas por modalidade:")
            for modalidade, total in modalidades:
                print(f"   • {modalidade}: {total}")
        
        if duplicatas:
            print(f"   ⚠️  URLs duplicadas encontradas: {len(duplicatas)}")
        
        if ultimas_vagas:
            print(f"\n📋 Últimas 5 vagas do Vagas.com:")
            for vaga in ultimas_vagas:
                print(f"   • {vaga[0]} - {vaga[1]} ({vaga[2]}) - {vaga[3]}")
        
        cursor.close()
        
    except Exception as e:
        print(f"❌ Erro ao verificar vagas salvas: {e}")

def limpar_duplicatas_banco(conn):
    """Remove duplicatas do banco mantendo apenas a mais recente de cada URL"""
    try:
        cursor = conn.cursor()
        
        # Encontra duplicatas
        cursor.execute("""
            SELECT url_vaga, COUNT(*) as total 
            FROM vagas_emprego 
            WHERE fonte = 'Vagas.com' 
            GROUP BY url_vaga 
            HAVING COUNT(*) > 1;
        """)
        duplicatas = cursor.fetchall()
        
        if not duplicatas:
            print("✅ Nenhuma duplicata encontrada!")
            return
        
        print(f"🧹 Encontradas {len(duplicatas)} URLs com duplicatas")
        
        # Remove duplicatas mantendo apenas a mais recente
        sql_remove_duplicatas = """
            DELETE FROM vagas_emprego 
            WHERE id NOT IN (
                SELECT DISTINCT ON (url_vaga) id
                FROM vagas_emprego 
                WHERE fonte = 'Vagas.com'
                ORDER BY url_vaga, data_coleta DESC
            ) AND fonte = 'Vagas.com';
        """
        
        cursor.execute(sql_remove_duplicatas)
        removidas = cursor.rowcount
        
        conn.commit()
        cursor.close()
        
        print(f"✅ {removidas} registros duplicados removidos!")
        
    except Exception as e:
        print(f"❌ Erro ao limpar duplicatas: {e}")
        conn.rollback()

def main():
    """Função principal"""
    print("🚀 SCRAPING VAGAS.COM - INICIANDO...")
    print("=" * 60)
    
    # URL base (São Paulo, sem filtro de modalidade)
    url_base = "https://www.vagas.com.br/vagas-de-sao-paulo?a%5B%5D=24&e%5B%5D=S%C3%A3o+Paulo"
    
    print(f"🎯 URL base: {url_base}")
    
    # Conecta ao banco
    conn = conectar_banco()
    if not conn:
        return
    
    try:
        # Estado inicial do banco
        print(f"\n📊 ESTADO INICIAL DO BANCO:")
        verificar_vagas_salvas(conn)
        
        # Gera URLs com diferentes modalidades
        urls_modalidades = construir_urls_modalidades(url_base)
        
        print(f"\n🎯 URLs GERADAS POR MODALIDADE:")
        for modalidade, url in urls_modalidades.items():
            print(f"   📍 {modalidade}: {url[:100]}...")
        
        # Confirma execução
        print(f"\n" + "=" * 60)
        resposta = input("🤔 Deseja iniciar o scraping de TODAS as modalidades? (s/n): ").lower()
        
        if resposta != 's':
            print("👋 Scraping cancelado pelo usuário.")
            return
        
        # Pergunta se quer limpar duplicatas primeiro
        resposta_dup = input("🧹 Deseja limpar duplicatas antes do scraping? (s/n): ").lower()
        if resposta_dup == 's':
            print(f"\n🧹 LIMPANDO DUPLICATAS...")
            limpar_duplicatas_banco(conn)
        
        # Inicia o scraping de todas as modalidades
        print(f"\n🔄 INICIANDO SCRAPING DE TODAS AS MODALIDADES...")
        print("=" * 60)
        
        todas_vagas_coletadas = []
        
        for modalidade, url in urls_modalidades.items():
            print(f"\n🎯 COLETANDO VAGAS: {modalidade.upper()}")
            print("-" * 40)
            
            vagas = fazer_scraping_vagas(url, max_carregamentos=3)  # 3 páginas por modalidade
            
            print(f"📊 {modalidade}: {len(vagas)} vagas coletadas")
            todas_vagas_coletadas.extend(vagas)
            
            if modalidade != list(urls_modalidades.keys())[-1]:
                print(f"⏱️  Pausa entre modalidades...")
                time.sleep(random.uniform(5, 10))
        
        print(f"\n📈 RESULTADO GERAL DO SCRAPING:")
        print(f"   📊 Total de vagas coletadas: {len(todas_vagas_coletadas)}")
        
        # Mostra estatísticas por modalidade
        modalidades_stats = {}
        for vaga in todas_vagas_coletadas:
            modalidade = vaga.get('modalidade', 'Não informado')
            modalidades_stats[modalidade] = modalidades_stats.get(modalidade, 0) + 1
        
        if modalidades_stats:
            print(f"\n📈 Vagas coletadas por modalidade:")
            for modalidade, count in sorted(modalidades_stats.items(), key=lambda x: x[1], reverse=True):
                print(f"   • {modalidade}: {count}")
        
        if todas_vagas_coletadas:
            # Salva no banco
            print(f"\n💾 SALVANDO NO SUPABASE...")
            salvar_vagas_supabase(conn, todas_vagas_coletadas)
            
            # Verifica estado final
            print(f"\n📊 ESTADO FINAL DO BANCO:")
            verificar_vagas_salvas(conn)
        else:
            print("⚠️  Nenhuma vaga foi coletada.")
        
    except KeyboardInterrupt:
        print(f"\n⏹️  Scraping interrompido pelo usuário.")
    except Exception as e:
        print(f"\n❌ Erro geral no scraping: {e}")
    
    finally:
        # Fecha conexão
        conn.close()
        print(f"\n🔌 Conexão com banco fechada.")
        print("=" * 60)
        print("✅ SCRAPING FINALIZADO!")

if __name__ == "__main__":
    main()