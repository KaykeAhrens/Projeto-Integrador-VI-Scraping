import json
import psycopg2
from groq import Groq
import time
from datetime import datetime, date
from pathlib import Path

# --- CONFIGURAÇÕES ---
CONNECTION_STRING = "postgresql://postgres.wnhqaiogzvvwrxcgfwsj:abkm@aws-1-sa-east-1.pooler.supabase.com:5432/postgres"
CHECKPOINT_ARQ = Path("vagas_empregos2.jsonl") # O arquivo gerado pelo scraper
API_KEY = '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' # Sua chave Groq

# --- FUNÇÕES (COPIADAS E ADAPTADAS DO SEU SCRAPER) ---

def groq_is_ti(client, vaga: dict, model: str = "llama-3.3-70b-versatile", max_retries: int = 3) -> bool:
    system = (
        "Você é um classificador de vagas. Responda ESTRITAMENTE em JSON válido com o formato: {\"is_ti\": true|false}. "
        "Considere TI como desenvolvimento de software, dados/ML, DevOps/Cloud, QA, segurança, suporte/infra, redes, DBA, análise de sistemas. "
        "Não é TI: vagas administrativas, financeiras, saúde, jurídico, RH genérico. Se duvidar, responda {\"is_ti\": false}."
    )
    payload = { "titulo_vaga": vaga.get("titulo_vaga"), "descricao": vaga.get("descricao") }
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Classifique a vaga abaixo:\n{json.dumps(payload, ensure_ascii=False)}"}
    ]
    for attempt in range(1, max_retries + 1):
        try:
            resp = client.chat.completions.create(
                model=model, messages=messages, temperature=0, response_format={"type": "json_object"}
            )
            data = json.loads(resp.choices[0].message.content or "{}")
            return bool(data.get("is_ti", False))
        except Exception as e:
            print(f"  ⚠️ Groq erro (tentativa {attempt}/{max_retries}): {e}")
            if 'rate_limit_exceeded' in str(e):
                print("  ⛔ Limite de taxa atingido. Pausando por 60 segundos...")
                time.sleep(60)
            else:
                time.sleep(5 * attempt)
    return False # Retorna False se todas as tentativas falharem

def get_conn():
    return psycopg2.connect(CONNECTION_STRING)

def _coerce_date(value):
    if not value or value == "Não informado": return None
    if isinstance(value, (datetime, date)): return value
    try: return datetime.fromisoformat(value).date()
    except: return None

def salvar_vaga_no_banco(conn, vaga: dict):
    sql_insert = """
        INSERT INTO vagas_emprego (
            titulo_vaga, empresa, localizacao, salario, descricao, requisitos, 
            beneficios, tipo_contrato, modalidade, data_publicacao, url_vaga, fonte
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (url_vaga) DO NOTHING;
    """
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql_insert, (
                vaga.get('titulo_vaga'), vaga.get('empresa'), vaga.get('localizacao'),
                vaga.get('salario'), vaga.get('descricao', '')[:5000], vaga.get('requisitos', '')[:2000],
                vaga.get('beneficios', '')[:1000], vaga.get('tipo_contrato'), vaga.get('modalidade'),
                _coerce_date(vaga.get('data_publicacao')), vaga.get('url_vaga'), vaga.get('fonte')
            ))
        conn.commit()
        return cursor.rowcount > 0 # Retorna True se inseriu, False se era duplicata
    except Exception as e:
        print(f"  ❌ Erro ao salvar no DB: {e}")
        conn.rollback()
        return False

# --- SCRIPT PRINCIPAL ---
def main():
    print("🚀 Iniciando o classificador e salvamento no banco de dados...")
    
    if not CHECKPOINT_ARQ.exists():
        print(f"❌ Arquivo '{CHECKPOINT_ARQ}' não encontrado. Execute o scraper primeiro.")
        return

    client = Groq(api_key=API_KEY)
    conn = get_conn()
    
    vagas_processadas = 0
    vagas_ti_identificadas = 0
    vagas_salvas_db = 0

    with CHECKPOINT_ARQ.open("r", encoding="utf-8") as f:
        for linha in f:
            if not linha.strip():
                continue
            
            vaga = json.loads(linha)
            vagas_processadas += 1
            print("-" * 20)
            print(f"🔍 Processando vaga {vagas_processadas}: {vaga.get('titulo_vaga')}")

            eh_ti = groq_is_ti(client, vaga)
            
            if eh_ti:
                vagas_ti_identificadas += 1
                print("  ✅ Vaga classificada como TI. Salvando no banco...")
                if salvar_vaga_no_banco(conn, vaga):
                    vagas_salvas_db += 1
                    print("  💾 Salva com sucesso!")
                else:
                    print("  🔄 Vaga já existia no banco (duplicata).")
            else:
                print("  ⛔ Vaga classificada como NÃO TI. Ignorando.")

            time.sleep(1.5) # <<< CONTROLE DE TAXA! Pausa entre cada chamada à API.

    conn.close()
    print("\n" + "="*60)
    print("✅ Processo de classificação finalizado!")
    print(f"  - Vagas lidas do arquivo: {vagas_processadas}")
    print(f"  - Vagas de TI identificadas: {vagas_ti_identificadas}")
    print(f"  - Vagas novas salvas no banco: {vagas_salvas_db}")
    print("="*60)

if __name__ == "__main__":
    main()