import requests
from bs4 import BeautifulSoup
from database.db import insert_job
import re

# -------- Função para limpar textos --------
def clean_text(text):
    return re.sub(r'\s+', ' ', text).strip()

# -------- Scraper do Empregos.com.br --------
def scrape_empregos(term, pages=1):
    saved = 0

    for page in range(1, pages + 1):
        url = f"https://www.empregos.com.br/vagas/{term}?pagina={page}"
        r = requests.get(url)
        soup = BeautifulSoup(r.text, "html.parser")

        resultados = soup.find_all("div", class_="vaga")

        for vaga in resultados:
            title_tag = vaga.find("a", class_="titulo")
            company_tag = vaga.find("span", class_="empresa")

            title = clean_text(title_tag.get_text()) if title_tag else "Não encontrado"
            company = clean_text(company_tag.get_text()) if company_tag else "Não informado"
            link = "https://www.empregos.com.br" + title_tag["href"] if title_tag else None

            insert_job("Empregos.com.br", title, company, link)
            saved += 1

    print(f"[Empregos.com.br] {saved} vagas salvas.")
    return saved


def scrape_empregos2(area, num_paginas):
    total_vagas = 0
    area_url = area.lower().replace(" ", "-")
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    
    for pagina in range(1, num_paginas + 1):
        if pagina == 1:
            url = f"https://www.empregos.com.br/vagas/{area_url}"
        else:
            url = f"https://www.empregos.com.br/vagas/{area_url}/{pagina}"
        
        try:
            response = requests.get(url, headers=headers, timeout=10)
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Tenta diferentes seletores
            vagas = (soup.select('.vaga-item') or 
                    soup.select('.job-item') or 
                    soup.select('a[href*="/vaga/"]') or 
                    soup.select('.card'))
            
            total_vagas += len(vagas)
            time.sleep(1)
            
        except:
            continue
    
    print(f"[Empregos.com] {total_vagas} vagas salvas.")
    return total_vagas
