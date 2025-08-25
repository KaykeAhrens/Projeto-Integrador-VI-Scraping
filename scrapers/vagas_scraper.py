import requests
from bs4 import BeautifulSoup
from database.db import insert_job
import re

# -------- Função para limpar textos --------
def clean_text(text):
    return re.sub(r'\s+', ' ', text).strip()

# -------- Scraper do Vagas.com --------
def scrape_vagas(term, pages=1):
    saved = 0
    for page in range(1, pages+1):
        url = f"https://www.vagas.com.br/vagas-de-{term}?pagina={page}"
        r = requests.get(url)
        soup = BeautifulSoup(r.text, "html.parser")

        resultados = soup.find_all("div", class_="informacoes-header")
        for vaga in resultados:
            title_tag = vaga.find("a", class_="link-detalhes-vaga")
            company_tag = vaga.find("span", class_="emprVaga")

            title = clean_text(title_tag.get_text()) if title_tag else "Não encontrado"
            company = clean_text(company_tag.get_text()) if company_tag else "Não informado"
            link = "https://www.vagas.com.br" + title_tag["href"] if title_tag else None

            insert_job("Vagas.com", title, company, link)
            saved += 1
    print(f"[Vagas.com] {saved} vagas salvas.")
    return saved