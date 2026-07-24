import re
import time
import requests
import gspread
from bs4 import BeautifulSoup
from google.oauth2.service_account import Credentials

# ==============================================================================
# ⚙️ CONFIGURAÇÃO DE TESTE
MODO_TESTE = True
LIMITE_TESTE = 10
# ==============================================================================

ORIGEM_SPREADSHEET_ID = "1UTlgbveIQP4CMNblsB9WDfNvKMdi17SI8l7EQer_GEs"
DESTINO_SPREADSHEET_ID = "1HwVDWliIufg3OTUhadyBBJ_0yhNmRBISYUh4_2_wO4U"

CABECALHO = [
    "Link Ficha",
    "Documentos", "Publicidades", "Participantes", "Lotes & Itens", "Contratos",
    "Aditivos", "LICITAÇÃO", "Nº do Processo Administrativo", "Regime",
    "Critério de Avaliação", "Elemento de Despesa", "Local de Abertura",
    "Observação", "Há itens exclusivos para EPP/ME?",
    "Há cote de participação para EPP/ME?", "Percentual de participação para EPP/ME",
    "Nas aquisições, há prioridade para as microempresas regionais ou locais?",
    "Contratação com utilização de recursos federais advindos de transferências voluntárias?",
    "Exercício", "Abertura", "Publicação", "Homologação", "Caráter Sigiloso",
    "Será Firmado Contrato", "Contratos_Data", "Aditivos_Data"
]

def criar_sessao_navegador():
    """Cria uma sessão que simula com precisão um navegador Chrome real."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1"
    })
    return session

def conectar_google_sheets():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    credentials = Credentials.from_service_account_file("credentials.json", scopes=scopes)
    return gspread.authorize(credentials)

def obter_links_origem(client):
    sheet = client.open_by_key(ORIGEM_SPREADSHEET_ID).sheet1
    dados = sheet.get_all_records()
    links = [str(linha.get("Link Ficha", "")).strip() for linha in dados if linha.get("Link Ficha")]
    links_validos = [url for url in links if url.startswith("http")]

    if MODO_TESTE:
        print(f"🧪 [MODO TESTE] Processando apenas os primeiros {LIMITE_TESTE} links.")
        return links_validos[:LIMITE_TESTE]
    return links_validos

def extrair_ficha(session, url_ficha, retentativas=3):
    """Acessa a URL da ficha e raspa os 26 campos."""
    for tentativa in range(1, retentativas + 1):
        try:
            time.sleep(1.2) # Pausa fundamental para evitar WAF/Rate Limit
            resp = session.get(url_ficha, timeout=25, allow_redirects=True)
            
            if resp.status_code == 200 and "MURAL DE LICITAÇÕES" in resp.text.upper():
                soup = BeautifulSoup(resp.content, "html.parser")
                dados = {k: "não informado" for k in CABECALHO}
                dados["Link Ficha"] = url_ficha

                # 1 a 6: Abas Superiores (badges)
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

                # 7: Número da Licitação
                try:
                    h5_lic = soup.find("h5", class_="text-blue")
                    if h5_lic:
                        dados["LICITAÇÃO"] = h5_lic.get_text(strip=True)
                except Exception:
                    pass

                # 8 a 18: Bloco Principal (bill-to)
                try:
                    bill_to = soup.find("div", class_="bill-to")
                    if bill_to:
                        for p in bill_to.find_all("p"):
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

                # 19 a 26: Bloco Lateral (bill-data)
                try:
                    bill_data = soup.find("div", class_="bill-data")
                    if bill_data:
                        mapeamento = [
                            ("Exercício", "Exercício"), ("Abertura", "Abertura"),
                            ("Publicação", "Publicação"), ("Homologação", "Homologação"),
                            ("Caráter Sigiloso", "Caráter Sigiloso"), ("Será Firmado Contrato", "Será Firmado Contrato"),
                            ("Contratos", "Contratos_Data"), ("Aditivos", "Aditivos_Data")
                        ]
                        for p in bill_data.find_all("p"):
                            txt = p.get_text(" ", strip=True)
                            for rotulo, chave_dest in mapeamento:
                                if rotulo.lower() in txt.lower() and ":" in txt:
                                    _, val = txt.split(":", 1)
                                    dados[chave_dest] = val.strip()
                                    break
                except Exception:
                    pass

                return [dados[col] for col in CABECALHO]
            else:
                print(f"⚠️ HTTP {resp.status_code} na tentativa {tentativa} para: {url_ficha}")

        except Exception as e:
            print(f"⚠️ Erro de conexão na tentativa {tentativa}: {e}")
            time.sleep(2)

    return [url_ficha] + ["ERRO / BLOQUEIO"] * 26

def executar():
    print("🔌 Conectando ao Google Sheets...")
    client = conectar_google_sheets()

    print("📖 Lendo links da planilha de origem...")
    links = obter_links_origem(client)
    total = len(links)

    if not links:
        print("⚠️ Nenhum link encontrado.")
        return

    print("🌐 Criando sessão de navegação...")
    session = criar_sessao_navegador()

    # Primeiro faz um 'warm-up' na home do site para gerar cookies válidos
    try:
        session.get("https://www.tcmpa.tc.br/mural-de-licitacoes/", timeout=15)
        time.sleep(1)
    except Exception:
        pass

    resultados = []
    print(f"🚀 Baixando {total} fichas sequencialmente...")
    
    for idx, url in enumerate(links, 1):
        print(f"⚡ [{idx}/{total}] Extraindo: {url}")
        linha = extrair_ficha(session, url)
        resultados.append(linha)

    print("📤 Enviando dados para 'Abas_Detalhes_Fato'...")
    sheet_destino = client.open_by_key(DESTINO_SPREADSHEET_ID).sheet1
    sheet_destino.clear()
    sheet_destino.update('A1', [CABECALHO])
    sheet_destino.append_rows(resultados)

    print("🎉 Teste concluído! Verifique a planilha 'Abas_Detalhes_Fato'.")

if __name__ == "__main__":
    executar()
