import requests
from bs4 import BeautifulSoup
import re
from urllib.parse import urljoin
"""from database.db import insert_job"""

url = "https://br.indeed.com/jobs?q=programador"
r = requests.get(url)
soup = BeautifulSoup(r.text, "html.parser")

# -------- Função para limpar textos --------
def clean_text(text):
    return re.sub(r'\s+', ' ', (text or '')).strip()

# procura cada card de vaga (li) e dentro dele o <a.jcs-JobTitle>
resultados = soup.find_all("li")

for vaga in resultados:
    title_tag = vaga.find("a", class_="jcs-JobTitle")
    company_tag = vaga.find("span", attrs={"data-testid": "company-name"})

    titulo = clean_text(title_tag.get_text()) if title_tag else "Não encontrado"
    empresa = clean_text(company_tag.get_text()) if company_tag else "Não informado"
    link = urljoin(r.url, title_tag.get("href")) if title_tag else None

    if titulo != "Não encontrado":
        print("Título:", titulo)
        print("Empresa:", empresa)
        print("Link:", link)
        print("-" * 50)
