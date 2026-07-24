import re
import time
import requests
import gspread
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from google.oauth2.service_account import Credentials

# ==============================================================================
# ⚙️ CONFIGURAÇÃO DE TESTE
# Mude MODO_TESTE para False quando quiser processar a base inteira!
MODO_TESTE = True
LIMITE_TESTE = 10
# ==============================================================================

# --- CONFIGURAÇÕES DAS PLANILHAS ---
ORIGEM_SPREADSHEET_ID = "1UTlgbveIQP4CMNblsB9WDfNvKMdi17SI8l7EQer_GEs"  # Base_Licitacoes_Principais
DESTINO_SPREADSHEET_ID = "1HwVDWliIufg3OTUhadyBBJ_0yhNmRBISYUh4_2_wO4U" # Abas_Detalhes_Fato

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.tcmpa.tc.br/mural-de-licitacoes/licitacoes/listagem"
}

MAX_WORKERS = 3

# Definição oficial dos 27 campos (Link + 26 campos)
CABECALHO = [
    "Link Ficha",                                                                     # Coluna A
    "Documentos", "Publicidades", "Participantes", "Lotes & Itens", "Contratos",      # 1 a 5
    "Aditivos", "LICITAÇÃO", "Nº do Processo Administrativo", "Regime",               # 6 a 9
    "Critério de Avaliação", "Elemento de Despesa", "Local de Abertura",              # 10 a 12
    "Observação", "Há itens exclusivos para EPP/ME?",                                 # 13 e 14
    "Há cote de participação para EPP/ME?", "Percentual de participação para EPP/ME",  # 15 e 16
    "Nas aquisições, há prioridade para as microempresas regionais ou locais?",       # 17
    "Contratação com utilização de recursos federais advindos de transferências voluntárias?", # 18
    "Exercício", "Abertura", "Publicação", "Homologação", "Caráter Sigiloso",          # 19 a 23
    "Será Firmado Contrato", "Contratos_Data", "Aditivos_Data"                        # 24 a 26
]

def conectar_google_sheets():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    credentials = Credentials.from_service_account_file("credentials.json", scopes=scopes)
    return gspread.authorize(credentials)

def obter_links_origem(client):
    """Acessa a planilha Base_Licitacoes_Principais e traz os links da coluna 'Link Ficha'."""
    sheet = client.open_by_key(ORIGEM_SPREADSHEET_ID).sheet1
    dados = sheet.get_all_records()
    links = [str(linha.get("Link Ficha", "")).strip() for linha in dados if linha.get("Link Ficha")]
    links_validos = [url for url in links if url.startswith("http")]

    if MODO_TESTE:
        print(f"🧪 [MODO TESTE ATIVO] Limitando a execução para as primeiras {LIMITE_TESTE} linhas.")
        return links_validos[:LIMITE_TESTE]
    
    return links_validos

def extrair_ficha_licitacao(url_ficha, retentativas=3):
    """Raspa os 26 campos de forma robusta e tolerante a erros."""
    for tentativa in range(1, retentativas + 1):
        try:
            time.sleep(0.5) # Pausa amigável para não sobrecarregar o servidor
            resp = requests.get(url_ficha, headers=HEADERS, timeout=20)
            
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.content, "html.parser")
                dados = {k: "não informado" for k in CABECALHO}
                dados["Link Ficha"] = url_ficha

                # --- 1 a 6: Abas Superiores ---
                try:
                    resumo_badges = soup.find_all("span", class_="resumo-qtd")
                    if len(resumo_badges) >= 6:
                        dados["Documentos"] = resumo_badges[0].get_text(strip=True)
                        dados["Publicidades"] = resumo_badges[1].get_text(strip=True)
                        dados["Participantes"] = resumo_badges[2].get_text(strip=True)
                        dados["Lotes & Itens"] = resumo_badges[3].get_text(strip=True)
                        dados["Contratos"] = resumo_badges[4].get_text(strip=True)
                        dados["Aditivos"] = resumo_badges[5].get_text(strip=True)
                except Exception:
                    pass

                # --- 7: Número da Licitação ---
                try:
                    h5_licitacao = soup.find("h5", class_="text-blue")
                    if h5_licitacao:
                        dados["LICITAÇÃO"] = h5_licitacao.get_text(strip=True)
                except Exception:
                    pass

                # --- 8 a 18: Processo Principal (div.bill-to) ---
                try:
                    bill_to = soup.find("div", class_="bill-to")
                    if bill_to:
                        p_tags = bill_to.find_all("p")
                        for p in p_tags:
                            texto = p.get_text(" ", strip=True)
                            if ":" in texto:
                                chave_bruta, valor = texto.split(":", 1)
                                chave_limpa = re.sub(r'^[>\s\W]+', '', chave_bruta).strip().lower()
                                valor_limpo = valor.strip()
                                
                                for campo_ref in CABECALHO[8:19]:
                                    if campo_ref.lower() in chave_limpa:
                                        dados[campo_ref] = valor_limpo
                                        break
                except Exception:
                    pass

                # --- 19 a 26: Bloco Lateral (div.bill-data) ---
                try:
                    bill_data = soup.find("div", class_="bill-data")
                    if bill_data:
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
                                    break
                except Exception:
                    pass

                return url_ficha, [dados[col] for col in CABECALHO]

            else:
                print(f"⚠️ HTTP Status {resp.status_code} na URL: {url_ficha} (tentativa {tentativa})")

        except Exception as e:
            time.sleep(2)

    return url_ficha, [url_ficha] + ["ERRO / BLOQUEIO"] * 26

def executar():
    print("🔌 Conectando à API do Google...")
    client = conectar_google_sheets()

    print("📖 Lendo links da planilha Base_Licitacoes_Principais...")
    links = obter_links_origem(client)
    total_links = len(links)
    print(f"🔗 Serão processados {total_links} links nesta execução.")

    if not links:
        print("⚠️ Nenhum link encontrado.")
        return

    print(f"🚀 Baixando fichas em paralelo (MAX_WORKERS = {MAX_WORKERS})...")
    resultados_dict = {}
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(extrair_ficha_licitacao, url): url for url in links}
        concluidos = 0
        for future in as_completed(futures):
            url_ficha, linha_dados = future.result()
            resultados_dict[url_ficha] = linha_dados
            concluidos += 1
            print(f"⚡ Progresso: {concluidos}/{total_links} fichas concluídas.")

    linhas_finais = [resultados_dict[url] for url in links if url in resultados_dict]

    print("📤 Enviando resultados para a planilha 'Abas_Detalhes_Fato'...")
    sheet_destino = client.open_by_key(DESTINO_SPREADSHEET_ID).sheet1
    
    sheet_destino.clear()
    sheet_destino.update('A1', [CABECALHO])
    sheet_destino.append_rows(linhas_finais)

    print("🎉 Teste finalizado com sucesso! Verifique a planilha 'Abas_Detalhes_Fato'.")

if __name__ == "__main__":
    executar()
