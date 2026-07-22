import time
import requests
import pandas as pd
from bs4 import BeautifulSoup

BASE_URL = "https://www.tcmpa.tc.br"
URL_PAGINA = "https://www.tcmpa.tc.br/mural-de-licitacoes/licitacoes/listagem?page={}&per-page=50"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def extrair_pagina(pagina):
    url = URL_PAGINA.format(pagina)
    print(f"--> Extraindo dados da página {pagina}...")
    
    try:
        # Timeout de 15 segundos evita que a execução fique presa
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"❌ Erro de conexão na página {pagina}: {e}")
        return None

    soup = BeautifulSoup(response.content, 'html.parser')
    
    div_tabela = soup.find('div', id='w0')
    if not div_tabela:
        return None
        
    table = div_tabela.find('table')
    if not table or not table.find('tbody'):
        return None

    rows = table.find('tbody').find_all('tr')
    dados_pagina = []

    for row in rows:
        cols = row.find_all('td')
        
        # Confere se a linha possui as 12 colunas da tabela
        if len(cols) >= 12:
            link_tag = cols[1].find('a')
            numero_texto = link_tag.get_text(strip=True) if link_tag else cols[1].get_text(strip=True)
            link_ficha = BASE_URL + link_tag['href'] if link_tag and 'href' in link_tag.attrs else ""

            item = {
                'Legislação': cols[0].get_text(strip=True),
                'Número': numero_texto,
                'Link Ficha': link_ficha,
                'Modalidade': cols[2].get_text(strip=True),
                'Tipo': cols[3].get_text(strip=True),
                'Objeto': cols[4].get_text(strip=True),
                'Data Abertura': cols[5].get_text(strip=True),
                'Data Publicação': cols[6].get_text(strip=True),
                'Município': cols[7].get_text(strip=True),
                'Órgão': cols[8].get_text(strip=True),
                'Situação': cols[9].get_text(strip=True),
                'Valor Referência (R$)': cols[10].get_text(strip=True), # Capturado!
                'Valor Adjudicado (R$)': cols[11].get_text(strip=True)  # Capturado!
            }
            dados_pagina.append(item)

    return dados_pagina

def executar_raspagem(max_paginas=5):
    """
    Busca as 5 primeiras páginas (250 licitações mais recentes).
    Aumente ou diminua 'max_paginas' se precisar de mais histórico.
    """
    todos_dados = []
    
    for pagina in range(1, max_paginas + 1):
        dados = extrair_pagina(pagina)
        if not dados:
            print(f"Fim da listagem ou falha na página {pagina}.")
            break
        todos_dados.extend(dados)
        time.sleep(1) # Pausa amigável de 1s para o servidor

    if todos_dados:
        df = pd.DataFrame(todos_dados)
        
        # Salva a tabela limpa
        df.to_csv("licitacoes_tcm_pa.csv", index=False, encoding="utf-8-sig")
        print(f"\n✅ Sucesso! Total de {len(df)} licitações salvas em 'licitacoes_tcm_pa.csv'.")
    else:
        print("\n⚠️ Nenhuma licitação foi extraída.")

if __name__ == "__main__":
    executar_raspagem(max_paginas=5)
