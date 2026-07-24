import re
import time
import requests
import gspread
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from google.oauth2.service_account import Credentials

# --- CONFIGURAÇÕES DAS PLANILHAS ---
ORIGEM_SPREADSHEET_ID = "1UTlgbveIQP4CMNblsB9WDfNvKMdi17SI8l7EQer_GEs"  # Base_Licitacoes_Principais
DESTINO_SPREADSHEET_ID = "1HwVDWliIufg3OTUhadyBBJ_0yhNmRBISYUh4_2_wO4U" # Abas_Detalhes_Fato

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# Quantidade de requisições em paralelo para acelerar o processo
MAX_WORKERS = 10

# Definição oficial dos 26 campos (em ordem exata)
CABECALHO = [
    "Link Ficha",                                                                     # Coluna A
    "Documentos", "Publicidades", "Participantes", "Lotes & Itens", "Contratos",      # Campos 1 a 6
    "Aditivos", "LICITAÇÃO", "Nº do Processo Administrativo", "Regime",               # Campos 6 a 9
    "Critério de Avaliação", "Elemento de Despesa", "Local de Abertura",              # Campos 10 a 12
    "Observação", "Há itens exclusivos para EPP/ME?",                                 # Campos 13 e 14
    "Há cote de participação para EPP/ME?", "Percentual de participação para EPP/ME",  # Campos 15 e 16
    "Nas aquisições, há prioridade para as microempresas regionais ou locais?",       # Campo 17
    "Contratação com utilização de recursos federais advindos de transferências voluntárias?", # Campo 18
    "Exercício", "Abertura", "Publicação", "Homologação", "Caráter Sigiloso",          # Campos 19 a 23
    "Será Firmado Contrato", "Contratos_Data", "Aditivos_Data"                        # Campos 24 a 26
]

def conectar_google_sheets():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    credentials = Credentials.from_service_account_file("credentials.json", scopes=scopes)
    return gspread.authorize(credentials)

def obter_links_origem(client):
    """Acessa a planilha Base_Licitacoes_Principais e busca todos os links da coluna 'Link Ficha'."""
    sheet = client.open_by_key(ORIGEM_SPREADSHEET_ID).sheet1
    dados = sheet.get_all_records()
    links = [linha.get("Link Ficha", "").strip() for linha in dados if linha.get("Link Ficha")]
    return [url for url in links if url.startswith("http")]

def extrair_ficha_licitacao(url_ficha, retentativas=3):
    """Raspa os 26 campos específicos de uma URL de ficha."""
    for _ in range(retentativas):
        try:
            resp = requests.get(url_ficha, headers=HEADERS, timeout=15)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.content, "html.parser")
                
                # Dicionário temporário dos dados raspados
                dados = {k: "N/A" for k in CABECALHO}
                dados["Link Ficha"] = url_ficha

                # --- 1 a 6: Quantidades das Abas Superiores ---
                resumo_badges = soup.find_all("span", class_="resumo-qtd")
                if len(resumo_badges) >= 6:
                    dados["Documentos"] = resumo_badges[0].get_text(strip=True)
                    dados["Publicidades"] = resumo_badges[1].get_text(strip=True)
                    dados["Participantes"] = resumo_badges[2].get_text(strip=True)
                    dados["Lotes & Itens"] = resumo_badges[3].get_text(strip=True)
                    dados["Contratos"] = resumo_badges[4].get_text(strip=True)
                    dados["Aditivos"] = resumo_badges[5].get_text(strip=True)

                # --- 7: Número da Licitação ---
                h5_licitacao = soup.find("h5", class_="text-blue")
                if h5_licitacao:
                    dados["LICITAÇÃO"] = h5_licitacao.get_text(strip=True)

                # --- 8 a 18: Processo Principal (seção bill-to) ---
                bill_to = soup.find("div", class_="bill-to")
                if bill_to:
                    for p in bill_to.find_all("p"):
                        texto = p.get_text(" ", strip=True)
                        if ":" in texto:
                            chave_bruta, valor = texto.split(":", 1)
                            chave_limpa = re.sub(r'^[>\s\W]+', '', chave_bruta).strip()
                            valor_limpo = valor.strip()
                            
                            # Mapeia dinamicamente pelos nomes das chaves
                            for campo_ref in CABECALHO[8:19]:
                                if campo_ref.lower() in chave_limpa.lower():
                                    dados[campo_ref] = valor_limpo
                                    break

                # --- 19 a 26: Bloco Lateral (bill-data) ---
                bill_data = soup.find("div", class_="bill-data")
                if bill_data:
                    # Mapeamento estático para o bloco de datas/situações
                    p_tags = bill_data.find_all("p")
                    mapeamento_lateral = [
                        ("Exercício", "Exercício"),
                        ("Abertura", "Abertura"),
                        ("Publicação", "Publicação"),
                        ("Homologação", "Homologação"),
                        ("Caráter Sigiloso", "Caráter Sigiloso"),
                        ("Será Firmado Contrato", "Será Firmado Contrato"),
                        ("Contratos", "Contratos_Data"),
                        ("Aditivos", "Aditivos_Data")
                    ]
                    
                    for p in p_tags:
                        txt = p.get_text(" ", strip=True)
                        for rotulo, chave_dest in mapeamento_lateral:
                            if rotulo.lower() in txt.lower() and ":" in txt:
                                _, val = txt.split(":", 1)
                                dados[chave_dest] = val.strip()

                # Retorna a linha formatada na ordem exata do cabeçalho
                return url_ficha, [dados[col] for col in CABECALHO]
        except Exception:
            time.sleep(2)
            
    return url_ficha, [url_ficha] + ["ERRO"] * 26

def executar():
    print("🔌 Conectando à API do Google...")
    client = conectar_google_sheets()

    print("📖 Lendo links da planilha Base_Licitacoes_Principais...")
    links = obter_links_origem(client)
    total_links = len(links)
    print(f"🔗 Encontrados {total_links} links para extração.")

    if not links:
        print("⚠️ Nenhum link encontrado. Encerrando.")
        return

    print(f"🚀 Iniciando extração com {MAX_WORKERS} conexões paralelas...")
    resultados_dict = {}
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(extrair_ficha_licitacao, url): url for url in links}
        concluidos = 0
        for future in as_completed(futures):
            url_ficha, linha_dados = future.result()
            resultados_dict[url_ficha] = linha_dados
            concluidos += 1
            if concluidos % 50 == 0 or concluidos == total_links:
                print(f"⚡ Progresso da extração das fichas: {concluidos}/{total_links}...")

    # Garante a ordenação exata conforme a tabela de origem
    linhas_finais = [resultados_dict[url] for url in links if url in resultados_dict]

    print("📤 Escrevendo dados na planilha 'Abas_Detalhes_Fato'...")
    sheet_destino = client.open_by_key(DESTINO_SPREADSHEET_ID).sheet1
    
    # Limpa a tabela de destino e rescreve cabeçalhos + dados extraídos
    sheet_destino.clear()
    sheet_destino.update('A1', [CABECALHO])

    # Envio em lotes de 2.000 linhas
    TAMANHO_LOTE = 2000
    for i in range(0, len(linhas_finais), TAMANHO_LOTE):
        lote = linhas_finais[i:i + TAMANHO_LOTE]
        sheet_destino.append_rows(lote)
        print(f"📊 Lote {i//TAMANHO_LOTE + 1} enviado ({len(lote)} linhas)...")
        time.sleep(1)

    print("🎉 Extração e gravação finalizadas com sucesso!")

if __name__ == "__main__":
    executar()
