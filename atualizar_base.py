import requests
from bs4 import BeautifulSoup
import pandas as pd

# URL base do portal de licitações
BASE_URL = "https://www.tcm.pa.gov.br"
TARGET_URL = "https://www.tcm.pa.gov.br/mural-de-licitacoes/licitacoes/listagem?page=1&per-page=30"

# User-Agent para evitar bloqueios de requisição simples
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def extrair_licitacoes(url):
    print(f"Fazendo requisição para: {url}...")
    
    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"Erro ao acessar a página: {e}")
        return None

    soup = BeautifulSoup(response.content, 'html.parser')
    
    # Seleciona a tabela de licitações dentro da div com ID 'w0'
    table = soup.find('div', id='w0').find('table') if soup.find('div', id='w0') else None
    
    if not table:
        print("Tabela de licitações não encontrada.")
        return None

    tbody = table.find('tbody')
    rows = tbody.find_all('tr')
    
    dados = []

    for row in rows:
        cols = row.find_all('td')
        
        # Garante que é uma linha de dados com o número de colunas esperado (12 colunas)
        if len(cols) >= 12:
            # Captura a tag <a> do número da licitação para extrair o link detalhado
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
                'Valor Referência (R$)': cols[10].get_text(strip=True),
                'Valor Adjudicado (R$)': cols[11].get_text(strip=True)
            }
            dados.append(item)

    # Converte em DataFrame
    df = pd.DataFrame(dados)
    return df

# Execução do script
if __name__ == "__main__":
    df_licitacoes = extrair_licitacoes(TARGET_URL)
    
    if df_licitacoes is not None and not df_licitacoes.empty:
        print(f"\nSucesso! {len(df_licitacoes)} itens extraídos.")
        print(df_licitacoes[['Número', 'Município', 'Situação', 'Valor Referência (R$)']].head())
        
        # Salva o resultado em Excel e CSV
        df_licitacoes.to_csv("licitacoes_tcm_pa.csv", index=False, encoding="utf-8-sig")
        print("\nDados salvos em 'licitacoes_tcm_pa.csv'.")
