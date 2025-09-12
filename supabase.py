import psycopg2
import random
from datetime import datetime, timedelta

# 🔴 COLE SUA CONNECTION STRING AQUI (substitua a linha abaixo)
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

def fazer_select(conn):
    """Faz select na tabela vagas_emprego"""
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM vagas_emprego;")
        total = cursor.fetchone()[0]
        print(f"📊 Total de vagas na tabela: {total}")
        
        # Mostra as últimas 5 vagas
        cursor.execute("""
            SELECT titulo_vaga, empresa, localizacao, salario, data_publicacao 
            FROM vagas_emprego 
            ORDER BY data_coleta DESC 
            LIMIT 5;
        """)
        
        vagas = cursor.fetchall()
        if vagas:
            print("\n📋 Últimas 5 vagas:")
            for vaga in vagas:
                print(f"  • {vaga[0]} - {vaga[1]} ({vaga[2]}) - {vaga[3]}")
        else:
            print("📋 Nenhuma vaga encontrada.")
            
        cursor.close()
        
    except Exception as e:
        print(f"❌ Erro no SELECT: {e}")

def gerar_dados_aleatorios():
    """Gera dados aleatórios para inserir na tabela"""
    
    titulos = [
        "Desenvolvedor Python Sênior",
        "Analista de Dados",
        "DevOps Engineer",
        "Desenvolvedor Full Stack",
        "Engenheiro de Machine Learning",
        "QA Automation",
        "Arquiteto de Software",
        "Desenvolvedor React",
        "Data Scientist",
        "Backend Developer Java"
    ]
    
    empresas = [
        "TechCorp",
        "InnovaSoft",
        "DataTech Solutions",
        "CloudFirst",
        "AI Dynamics",
        "CodeMasters",
        "StartupTech",
        "DevSolutions",
        "TechnoLogic",
        "FutureSoft"
    ]
    
    localizacoes = [
        "São Paulo, SP",
        "Rio de Janeiro, RJ",
        "Belo Horizonte, MG",
        "Porto Alegre, RS",
        "Curitiba, PR",
        "Florianópolis, SC",
        "Brasília, DF",
        "Remote",
        "Recife, PE",
        "Salvador, BA"
    ]
    
    salarios = [
        "R$ 8.000 - R$ 12.000",
        "R$ 10.000 - R$ 15.000",
        "R$ 6.000 - R$ 9.000",
        "R$ 12.000 - R$ 18.000",
        "R$ 7.500 - R$ 11.000",
        "R$ 15.000 - R$ 20.000",
        "A combinar",
        "R$ 5.000 - R$ 8.000",
        "R$ 20.000 - R$ 25.000"
    ]
    
    descricoes = [
        "Desenvolvimento de aplicações web usando tecnologias modernas.",
        "Análise de dados e criação de dashboards para tomada de decisões.",
        "Implementação e manutenção de infraestrutura cloud.",
        "Desenvolvimento full stack com foco em experiência do usuário.",
        "Criação de modelos de machine learning para soluções inovadoras.",
        "Automação de testes e garantia de qualidade do software.",
        "Design e arquitetura de sistemas escaláveis e robustos.",
        "Desenvolvimento frontend com React e tecnologias modernas.",
        "Extração de insights de dados para estratégias de negócio.",
        "Desenvolvimento backend com Java e Spring Framework."
    ]
    
    requisitos = [
        "3+ anos de experiência, Python, Django/Flask, SQL",
        "Conhecimento em SQL, Python/R, Power BI ou Tableau",
        "Docker, Kubernetes, AWS/Azure, Linux",
        "React, Node.js, MongoDB, APIs REST",
        "Python, TensorFlow/PyTorch, estatística, SQL",
        "Selenium, Cypress, Jest, metodologias ágeis",
        "Arquitetura de software, microserviços, liderança técnica",
        "React, JavaScript ES6+, HTML5, CSS3, Git",
        "Python, pandas, numpy, machine learning, visualização",
        "Java 11+, Spring Boot, REST APIs, banco de dados"
    ]
    
    beneficios = [
        "Vale refeição, plano de saúde, home office flexível",
        "Plano médico/odontológico, auxílio educação, gympass",
        "Trabalho remoto, horário flexível, vale alimentação",
        "Plano de carreira, treinamentos, ambiente descontraído",
        "Auxílio home office, day off aniversário, participação nos lucros",
        "Convênio médico, seguro de vida, café liberado",
        "Stock options, plano de saúde premium, férias flexíveis",
        "Vale cultura, academia corporativa, happy hour",
        "Auxílio creche, plano dental, clube de benefícios",
        "Carro da empresa, notebook, internet reembolsada"
    ]
    
    tipos_contrato = ["CLT", "PJ", "CLT", "PJ", "CLT", "Estágio", "Freelancer"]
    modalidades = ["Presencial", "Remoto", "Híbrido", "Remoto", "Híbrido"]
    fontes = ["LinkedIn", "Indeed", "InfoJobs", "Programathor", "GeekHunter"]
    
    # Gera data aleatória nos últimos 30 dias
    data_base = datetime.now().date()
    dias_aleatorios = random.randint(1, 30)
    data_publicacao = data_base - timedelta(days=dias_aleatorios)
    
    return {
        'titulo_vaga': random.choice(titulos),
        'empresa': random.choice(empresas),
        'localizacao': random.choice(localizacoes),
        'salario': random.choice(salarios),
        'descricao': random.choice(descricoes),
        'requisitos': random.choice(requisitos),
        'beneficios': random.choice(beneficios),
        'tipo_contrato': random.choice(tipos_contrato),
        'modalidade': random.choice(modalidades),
        'data_publicacao': data_publicacao,
        'url_vaga': f"https://exemplo.com/vaga/{random.randint(1000, 9999)}",
        'fonte': random.choice(fontes)
    }

def inserir_dados_aleatorios(conn, quantidade=5):
    """Insere dados aleatórios na tabela vagas_emprego"""
    try:
        cursor = conn.cursor()
        
        sql_insert = """
        INSERT INTO vagas_emprego (
            titulo_vaga, empresa, localizacao, salario, descricao, 
            requisitos, beneficios, tipo_contrato, modalidade, 
            data_publicacao, url_vaga, fonte
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        );
        """
        
        vagas_inseridas = 0
        for i in range(quantidade):
            dados = gerar_dados_aleatorios()
            
            cursor.execute(sql_insert, (
                dados['titulo_vaga'],
                dados['empresa'],
                dados['localizacao'],
                dados['salario'],
                dados['descricao'],
                dados['requisitos'],
                dados['beneficios'],
                dados['tipo_contrato'],
                dados['modalidade'],
                dados['data_publicacao'],
                dados['url_vaga'],
                dados['fonte']
            ))
            vagas_inseridas += 1
        
        conn.commit()
        cursor.close()
        print(f"✅ {vagas_inseridas} vagas inseridas com sucesso!")
        
    except Exception as e:
        print(f"❌ Erro ao inserir dados: {e}")
        conn.rollback()

def main():
    """Função principal"""
    print("🚀 Iniciando conexão com Supabase...")
    print("=" * 50)
    
    # Conecta ao banco
    conn = conectar_banco()
    if not conn:
        return
    
    try:
        # Faz SELECT inicial
        print("\n📋 DADOS ATUAIS NA TABELA:")
        fazer_select(conn)
        
        # Pergunta se quer inserir dados
        print("\n" + "=" * 50)
        resposta = input("Deseja inserir 5 vagas aleatórias? (s/n): ").lower()
        
        if resposta == 's':
            print("\n💾 INSERINDO DADOS...")
            inserir_dados_aleatorios(conn, 5)
            
            # Faz SELECT novamente para mostrar os novos dados
            print("\n📋 DADOS APÓS INSERÇÃO:")
            fazer_select(conn)
        else:
            print("👋 Ok, não inserindo dados.")
        
    except Exception as e:
        print(f"❌ Erro geral: {e}")
    
    finally:
        # Fecha a conexão
        conn.close()
        print("\n🔌 Conexão fechada.")
        print("=" * 50)

if __name__ == "__main__":
    main()