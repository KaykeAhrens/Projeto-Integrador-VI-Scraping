import requests
from bs4 import BeautifulSoup
from database.db import insert_job
import re

# -------- Função para limpar textos --------
def clean_text(text):
    return re.sub(r'\s+', ' ', text).strip()

# -------- Scraper do Programathor --------
def scrape_programathor(num_paginas):
    total_vagas = 0
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    
    for pagina in range(1, num_paginas + 1):
        if pagina == 1:
            url = "https://programathor.com.br/jobs"
        else:
            url = f"https://programathor.com.br/jobs?page={pagina}"
        
        try:
            response = requests.get(url, headers=headers, timeout=10)
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Tenta diferentes seletores
            vagas = (soup.select('.job-item') or 
                    soup.select('.vaga-item') or 
                    soup.select('a[href*="/jobs/"]') or 
                    soup.select('.card') or
                    soup.select('article'))
            
            total_vagas += len(vagas)
            time.sleep(1)
            
        except:
            continue
    
    print(f"[Programathor.com] {total_vagas} vagas salvas.")
    
    return total_vagas