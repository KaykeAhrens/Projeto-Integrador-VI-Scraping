import sqlite3
import pandas as pd
from datetime import datetime
import os

class SQLiteViewer:
    def __init__(self, db_path="jobs.db"):
        self.db_path = db_path
    
    def view_all_jobs(self, limit=None):
        """Mostra todas as vagas de forma organizada"""
        conn = sqlite3.connect(self.db_path)
        
        query = """
        SELECT 
            id,
            source,
            title,
            company,
            link,
            datetime(created_at, 'localtime') as created_at
        FROM jobs 
        ORDER BY created_at DESC
        """
        
        if limit:
            query += f" LIMIT {limit}"
        
        cursor = conn.cursor()
        cursor.execute(query)
        jobs = cursor.fetchall()
        conn.close()
        
        if not jobs:
            print("❌ Nenhuma vaga encontrada no banco!")
            return
        
        print(f"📊 Total de vagas encontradas: {len(jobs)}")
        print("=" * 100)
        
        for job in jobs:
            id_job, source, title, company, link, created_at = job
            print(f"ID: {id_job}")
            print(f"📍 Fonte: {source}")
            print(f"💼 Título: {title}")
            print(f"🏢 Empresa: {company}")
            print(f"🔗 Link: {link if link else 'N/A'}")
            print(f"📅 Data: {created_at}")
            print("-" * 100)
    
    def view_summary(self):
        """Mostra um resumo estatístico das vagas"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Total geral
        cursor.execute("SELECT COUNT(*) FROM jobs")
        total = cursor.fetchone()[0]
        
        # Por fonte
        cursor.execute("SELECT source, COUNT(*) FROM jobs GROUP BY source ORDER BY COUNT(*) DESC")
        by_source = cursor.fetchall()
        
        # Últimas 24 horas
        cursor.execute("SELECT COUNT(*) FROM jobs WHERE datetime(created_at) > datetime('now', '-1 day')")
        last_24h = cursor.fetchone()[0]
        
        # Empresas mais ativas
        cursor.execute("SELECT company, COUNT(*) as count FROM jobs GROUP BY company ORDER BY count DESC LIMIT 10")
        top_companies = cursor.fetchall()
        
        conn.close()
        
        print("📈 RESUMO DAS VAGAS")
        print("=" * 50)
        print(f"Total de vagas: {total}")
        print(f"Vagas nas últimas 24h: {last_24h}")
        print()
        
        print("📊 Por fonte:")
        for source, count in by_source:
            print(f"  {source}: {count} vagas")
        print()
        
        print("🏢 Top 10 empresas:")
        for company, count in top_companies:
            print(f"  {company}: {count} vagas")
    
    def search_jobs(self, keyword, source=None):
        """Busca vagas por palavra-chave"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if source:
            query = """
            SELECT id, source, title, company, link, datetime(created_at, 'localtime') as created_at
            FROM jobs 
            WHERE (title LIKE ? OR company LIKE ?) AND source = ?
            ORDER BY created_at DESC
            """
            cursor.execute(query, (f"%{keyword}%", f"%{keyword}%", source))
        else:
            query = """
            SELECT id, source, title, company, link, datetime(created_at, 'localtime') as created_at
            FROM jobs 
            WHERE title LIKE ? OR company LIKE ?
            ORDER BY created_at DESC
            """
            cursor.execute(query, (f"%{keyword}%", f"%{keyword}%"))
        
        results = cursor.fetchall()
        conn.close()
        
        if not results:
            print(f"❌ Nenhuma vaga encontrada para '{keyword}'")
            return
        
        print(f"🔍 Resultados para '{keyword}': {len(results)} vagas")
        print("=" * 100)
        
        for job in results:
            id_job, source, title, company, link, created_at = job
            print(f"ID: {id_job} | {source}")
            print(f"💼 {title}")
            print(f"🏢 {company}")
            print(f"📅 {created_at}")
            if link:
                print(f"🔗 {link}")
            print("-" * 100)
    
    def export_to_excel(self, filename="vagas.xlsx"):
        """Exporta para Excel usando pandas"""
        try:
            conn = sqlite3.connect(self.db_path)
            
            # Carrega dados em DataFrame
            df = pd.read_sql_query("""
                SELECT 
                    source as 'Fonte',
                    title as 'Título',
                    company as 'Empresa',
                    link as 'Link',
                    datetime(created_at, 'localtime') as 'Data Criação'
                FROM jobs 
                ORDER BY created_at DESC
            """, conn)
            
            conn.close()
            
            # Salva em Excel
            df.to_excel(filename, index=False, engine='openpyxl')
            print(f"✅ Dados exportados para {filename}")
            print(f"📊 Total de {len(df)} vagas exportadas")
            
        except ImportError:
            print("❌ Para exportar Excel, instale: pip install pandas openpyxl")
        except Exception as e:
            print(f"❌ Erro ao exportar: {e}")
    
    def view_with_pandas(self):
        """Visualiza usando pandas (mais bonito)"""
        try:
            conn = sqlite3.connect(self.db_path)
            
            df = pd.read_sql_query("""
                SELECT 
                    id as 'ID',
                    source as 'Fonte',
                    title as 'Título',
                    company as 'Empresa',
                    datetime(created_at, 'localtime') as 'Data'
                FROM jobs 
                ORDER BY created_at DESC
                LIMIT 20
            """, conn)
            
            conn.close()
            
            print("📋 ÚLTIMAS 20 VAGAS (com pandas):")
            print("=" * 100)
            
            # Configura pandas para mostrar mais colunas
            pd.set_option('display.max_columns', None)
            pd.set_option('display.width', None)
            pd.set_option('display.max_colwidth', 50)
            
            print(df.to_string(index=False))
            
        except ImportError:
            print("❌ Para usar pandas, instale: pip install pandas")
        except Exception as e:
            print(f"❌ Erro: {e}")
    
    def interactive_menu(self):
        """Menu interativo para navegar pelas vagas"""
        while True:
            print("\n" + "="*50)
            print("🔍 VISUALIZADOR DE VAGAS SQLite")
            print("="*50)
            print("1. Ver todas as vagas (últimas 20)")
            print("2. Ver resumo estatístico")
            print("3. Buscar vagas por palavra-chave")
            print("4. Ver com pandas (bonito)")
            print("5. Exportar para Excel")
            print("6. Ver todas (sem limite)")
            print("0. Sair")
            print("-"*50)
            
            choice = input("Escolha uma opção: ").strip()
            
            if choice == "1":
                self.view_all_jobs(limit=20)
            
            elif choice == "2":
                self.view_summary()
            
            elif choice == "3":
                keyword = input("Digite a palavra-chave: ").strip()
                if keyword:
                    source = input("Fonte específica (Enter para todas): ").strip()
                    source = source if source else None
                    self.search_jobs(keyword, source)
            
            elif choice == "4":
                self.view_with_pandas()
            
            elif choice == "5":
                filename = input("Nome do arquivo (vagas.xlsx): ").strip()
                filename = filename if filename else "vagas.xlsx"
                self.export_to_excel(filename)
            
            elif choice == "6":
                confirm = input("⚠️  Isso pode mostrar muitas vagas. Continuar? (s/N): ")
                if confirm.lower() == 's':
                    self.view_all_jobs()
            
            elif choice == "0":
                print("👋 Até logo!")
                break
            
            else:
                print("❌ Opção inválida!")
            
            input("\nPressione Enter para continuar...")


# ============================================
# FUNÇÕES RÁPIDAS PARA USAR NO TERMINAL
# ============================================

def quick_view(db_path="jobs.db", limit=10):
    """Visualização rápida - use: quick_view()"""
    viewer = SQLiteViewer(db_path)
    viewer.view_all_jobs(limit)

def quick_search(keyword, db_path="jobs.db"):
    """Busca rápida - use: quick_search('python')"""
    viewer = SQLiteViewer(db_path)
    viewer.search_jobs(keyword)

def quick_summary(db_path="jobs.db"):
    """Resumo rápido - use: quick_summary()"""
    viewer = SQLiteViewer(db_path)
    viewer.view_summary()

def check_database(db_path="jobs.db"):
    """Verifica se o banco existe e tem dados"""
    if not os.path.exists(db_path):
        print(f"❌ Banco de dados '{db_path}' não encontrado!")
        print("💡 Execute o scraper primeiro para criar o banco.")
        return False
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT COUNT(*) FROM jobs")
        count = cursor.fetchone()[0]
        
        if count == 0:
            print(f"⚠️  Banco '{db_path}' existe mas está vazio!")
            print("💡 Execute o scraper para adicionar vagas.")
        else:
            print(f"✅ Banco '{db_path}' encontrado com {count} vagas!")
        
        conn.close()
        return count > 0
        
    except sqlite3.OperationalError:
        print(f"❌ Erro ao acessar o banco '{db_path}'")
        conn.close()
        return False


# ============================================
# EXEMPLO DE USO
# ============================================

if __name__ == "__main__":
    # Verifica se o banco existe
    if check_database():
        # Inicia o menu interativo
        viewer = SQLiteViewer()
        viewer.interactive_menu()
    
    # Ou use as funções rápidas:
    # quick_view()           # Ver últimas 10 vagas
    # quick_search("python") # Buscar vagas com "python"
    # quick_summary()        # Ver estatísticas