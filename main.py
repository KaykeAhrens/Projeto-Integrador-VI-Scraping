from scrapers import vagas_scraper
from scrapers import programathor_scraper
from scrapers import empregos_scraper
from database.db import create_table

def scrape_all():
    print("Criando tabela...")
    create_table()

    total_saved = 0

    # ----- Rodando scrapers -----
    total_saved += vagas_scraper.scrape_vagas("desenvolvedor", pages=2)
    total_saved += programathor_scraper.scrape_programathor(num_paginas=2)
    total_saved += empregos_scraper.scrape_empregos2("desenvolvedor", num_paginas=2)
    
    # Se futuramente adicionar outros scrapers:
    # from scrapers import indeed_scraper
    # total_saved += indeed_scraper.scrape_indeed("desenvolvedor", pages=2)

    print("✅ Coleta finalizada!")
    print(f"Total de vagas salvas: {total_saved}")

if __name__ == "__main__":
    scrape_all()
