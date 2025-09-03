import requests
from bs4 import BeautifulSoup
import sqlite3
import hashlib
import re
from datetime import datetime
import os

class JobScraper:
    def __init__(self, db_path="jobs.db"):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Inicializa o banco de dados SQLite"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                link TEXT,
                job_hash TEXT UNIQUE NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Índice para busca rápida por hash
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_job_hash ON jobs(job_hash)
        ''')
        
        conn.commit()
        conn.close()
    
    def generate_job_hash(self, title, company, source):
        """Gera um hash único baseado no título, empresa e fonte"""
        # Normaliza os textos para evitar duplicatas por diferenças mínimas
        normalized_title = re.sub(r'\s+', ' ', title.lower().strip())
        normalized_company = re.sub(r'\s+', ' ', company.lower().strip())
        
        hash_input = f"{source}:{normalized_title}:{normalized_company}"
        return hashlib.md5(hash_input.encode('utf-8')).hexdigest()
    
    def job_exists(self, job_hash):
        """Verifica se a vaga já existe no banco"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT id FROM jobs WHERE job_hash = ?", (job_hash,))
        exists = cursor.fetchone() is not None
        
        conn.close()
        return exists
    
    def insert_job(self, source, title, company, link=None):
        """Insere uma nova vaga no banco (só se não existir)"""
        job_hash = self.generate_job_hash(title, company, source)
        
        if self.job_exists(job_hash):
            return False  # Vaga já existe
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO jobs (source, title, company, link, job_hash)
                VALUES (?, ?, ?, ?, ?)
            ''', (source, title, company, link, job_hash))
            
            conn.commit()
            return True  # Vaga inserida com sucesso
        except sqlite3.IntegrityError:
            return False  # Erro de duplicata (não deveria acontecer)
        finally:
            conn.close()
    
    def get_jobs_count(self, source=None):
        """Retorna o número de vagas no banco"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if source:
            cursor.execute("SELECT COUNT(*) FROM jobs WHERE source = ?", (source,))
        else:
            cursor.execute("SELECT COUNT(*) FROM jobs")
        
        count = cursor.fetchone()[0]
        conn.close()
        return count
    
    def clean_text(self, text):
        """Limpa e normaliza textos"""
        if not text:
            return ""
        return re.sub(r'\s+', ' ', text.strip())
    
    def contains_keywords(self, text, keywords):
        """Verifica se o texto contém pelo menos uma das palavras-chave como palavras completas"""
        if not text or not keywords:
            return False
        
        text_lower = text.lower()
        
        for keyword in keywords:
            keyword_lower = keyword.lower().strip()
            
            # Para palavras de 1-2 caracteres (como "TI", "IA"), usa busca mais rigorosa
            if len(keyword_lower) <= 2:
                # Usa regex para buscar palavra completa com delimitadores
                pattern = r'\b' + re.escape(keyword_lower) + r'\b'
                if re.search(pattern, text_lower):
                    return True
            else:
                # Para palavras maiores, mantém a busca simples mas com espaços
                # Verifica se a palavra aparece isolada ou com espaços/pontuação
                pattern = r'(?<!\w)' + re.escape(keyword_lower) + r'(?!\w)'
                if re.search(pattern, text_lower):
                    return True
        
        return False
    
    def scrape_vagas(self, keywords, pages=1):
        """
        Scraper do Vagas.com com filtros por palavras-chave
        
        Args:
            keywords: string ou lista de palavras-chave para filtrar
            pages: número de páginas para percorrer
        """
        # Converte keywords para lista se for string
        if isinstance(keywords, str):
            keywords = [keywords]
        
        # Remove espaços e converte para minúsculo
        keywords = [k.strip().lower() for k in keywords if k.strip()]
        
        if not keywords:
            print("❌ Nenhuma palavra-chave válida fornecida!")
            return {'saved': 0, 'duplicates': 0, 'errors': 0, 'filtered': 0, 'total': 0}
        
        saved = 0
        duplicates = 0
        errors = 0
        filtered_out = 0
        
        print(f"[Vagas.com] Iniciando scraping com filtros: {', '.join(keywords)}")
        print(f"[Vagas.com] Fazendo busca para cada palavra-chave - {pages} página(s) cada")
        
        # 🔄 BUSCA POR CADA PALAVRA-CHAVE
        for keyword_index, keyword in enumerate(keywords, 1):
            search_term = keyword.replace(' ', '-')
            print(f"\n🔍 [{keyword_index}/{len(keywords)}] Buscando por: '{keyword}'")
            
            for page in range(1, pages + 1):
                try:
                    url = f"https://www.vagas.com.br/vagas-de-{search_term}?pagina={page}"
                    print(f"  📄 Página {page}...")
                    
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                    }
                    
                    r = requests.get(url, headers=headers, timeout=10)
                    r.raise_for_status()
                    
                    soup = BeautifulSoup(r.text, "html.parser")
                    resultados = soup.find_all("div", class_="informacoes-header")
                    
                    if not resultados:
                        print(f"    ℹ️ Nenhuma vaga encontrada na página {page}")
                        continue
                    
                    for vaga in resultados:
                        try:
                            title_tag = vaga.find("a", class_="link-detalhes-vaga")
                            company_tag = vaga.find("span", class_="emprVaga")
                            
                            title = self.clean_text(title_tag.get_text()) if title_tag else "Não encontrado"
                            company = self.clean_text(company_tag.get_text()) if company_tag else "Não informado"
                            link = "https://www.vagas.com.br" + title_tag["href"] if title_tag and title_tag.get("href") else None
                            
                            # Pula vagas sem informações essenciais
                            if title == "Não encontrado" or company == "Não informado":
                                continue
                            
                            # 🔍 FILTRO: Verifica se contém alguma palavra-chave no título
                            if not self.contains_keywords(title, keywords):
                                filtered_out += 1
                                print(f"    🚫 Filtrada: {title} - {company}")
                                continue
                            
                            # Tenta inserir a vaga (só passa pelo filtro)
                            if self.insert_job("Vagas.com", title, company, link):
                                saved += 1
                                print(f"    ✅ Nova vaga: {title} - {company}")
                            else:
                                duplicates += 1
                                print(f"    ⚠️ Duplicata: {title} - {company}")
                        
                        except Exception as e:
                            errors += 1
                            print(f"    ❌ Erro ao processar vaga: {e}")
                
                except requests.RequestException as e:
                    print(f"    🌐 Erro na página {page}: {e}")
                    errors += 1
                
                except Exception as e:
                    print(f"    ⚠️ Erro inesperado na página {page}: {e}")
                    errors += 1
        
        total_jobs = self.get_jobs_count("Vagas.com")
        
        print(f"\n📊 [Vagas.com] Resumo Final:")
        print(f"  • Palavras-chave usadas: {', '.join(keywords)}")
        print(f"  • Vagas novas salvas: {saved}")
        print(f"  • Duplicatas ignoradas: {duplicates}")
        print(f"  • Vagas filtradas (sem palavra-chave): {filtered_out}")
        print(f"  • Erros encontrados: {errors}")
        print(f"  • Total de vagas no banco (Vagas.com): {total_jobs}")
        
        return {
            'saved': saved,
            'duplicates': duplicates,
            'errors': errors,
            'filtered': filtered_out,
            'total': total_jobs
        }
    
    def export_to_csv(self, filename="vagas_export.csv"):
        """Exporta todas as vagas para CSV"""
        import csv
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT source, title, company, link, created_at 
            FROM jobs 
            ORDER BY created_at DESC
        ''')
        
        rows = cursor.fetchall()
        conn.close()
        
        with open(filename, 'w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow(['Fonte', 'Título', 'Empresa', 'Link', 'Data'])
            writer.writerows(rows)
        
        print(f"📄 Dados exportados para {filename}")
    
    def search_jobs(self, keyword, source=None):
        """Busca vagas por palavra-chave"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        query = "SELECT * FROM jobs WHERE (title LIKE ? OR company LIKE ?)"
        params = [f"%{keyword}%", f"%{keyword}%"]
        
        if source:
            query += " AND source = ?"
            params.append(source)
        
        query += " ORDER BY created_at DESC"
        
        cursor.execute(query, params)
        results = cursor.fetchall()
        conn.close()
        
        return results
    
    def clear_database(self):
        """Limpa todas as vagas do banco (útil para testes)"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM jobs")
        conn.commit()
        conn.close()
        
        print("🗑️ Banco de dados limpo!")

# -------- Exemplo de uso --------
if __name__ == "__main__":
    # Inicializa o scraper
    scraper = JobScraper()
    
    # Opção 1: Uma palavra-chave
    # result = scraper.scrape_vagas("programador", pages=3)
    
    # Opção 2: Múltiplas palavras-chave focadas em Dados e Programação
    keywords = [
        # Programação Geral
        "programador", "desenvolvedor", "TI", "tecnologia", "it", "IT", "ti", "tecnologia da informação",
        "sistemas", "engenheiro de software", "dados", "inteligência de dados", "data",
        
        # Linguagens de Programação
        "python", "java", "javascript", "c++", "c#", "react", "angular", "node", "laravel", "django",
        
        # Áreas de Desenvolvimento
        "full stack", "backend", "frontend", "mobile",
        
        # Data Science & Analytics
        "data scientist", "cientista de dados", "analista de dados", 
        "data analyst", "engenheiro de dados", "data engineer",
        "machine learning", "ml", "deep learning", "ai", 
        "inteligência artificial", "big data", "analytics",
        "analista de sistemas", "business intelligence", "bi", "BI",
        
        # Bancos de Dados
        "sql", "postgresql", "mysql", "mongodb", "nosql",
        "database", "dba", "data warehouse", "snowflake",
        
        # Cloud & DevOps (relacionado a dados)
        "devops", "cloud", "aws", "azure", "gcp", "google cloud", "docker", "kubernetes"
    ]
    result = scraper.scrape_vagas(keywords, pages=10)
    
    # Exporta para CSV (opcional)
    scraper.export_to_csv("minhas_vagas.csv")