import pandas as pd
import unicodedata
import re

print("Iniciando a comparação das bases...")

# 1. Caminhos exatos baseados na sua estrutura
arquivo_novo = "saídas/resultado_aprovadores_final.xlsx"
arquivo_antigo = "dados/lemontech_antiga.xlsx" 
arquivo_relatorio = "saídas/relatorio_comparacao.xlsx"

def normalizar(nome):
    """Normaliza os nomes para evitar que acentos acusem diferenças falsas"""
    if pd.isna(nome): return ""
    n = str(nome)
    n = unicodedata.normalize('NFKD', n).encode('ASCII', 'ignore').decode('ASCII')
    n = re.sub(r'[^a-zA-Z0-9\s]', ' ', n)
    return re.sub(r'\s+', ' ', n).strip().upper()

# 2. Lendo as bases
print("Lendo os arquivos Excel (isso pode levar alguns segundos)...")
df_novo = pd.read_excel(arquivo_novo)
df_antigo = pd.read_excel(arquivo_antigo)

# Remove duplicatas da antiga (já que ela repetia o CC para as regras 'S' e 'N')
df_antigo = df_antigo.drop_duplicates(subset=["Centro de custo"])

# 3. Cruzando os dados pelo Centro de Custo
print("Cruzando os dados...")
df_novo["Centro de Custo"] = df_novo["Centro de Custo"].astype(str).str.strip()
df_antigo["Centro de custo"] = df_antigo["Centro de custo"].astype(str).str.strip()

df_comparacao = pd.merge(
    df_novo, 
    df_antigo[["Centro de custo", "Aprovador", "Aprovador do aprovador"]], 
    left_on="Centro de Custo", 
    right_on="Centro de custo", 
    how="left"
)

# 4. Lógica de Comparação
resultados = []
for index, linha in df_comparacao.iterrows():
    cc = linha["Centro de Custo"]
    aprovador_novo = normalizar(linha["Aprovador (Diretor)"])
    aprovador_antigo = normalizar(linha["Aprovador"])
    
    if pd.isna(linha["Aprovador"]):
        status = "NOVO CC (Não existia na entrega do dia 17)"
    elif aprovador_novo == aprovador_antigo:
        status = "IGUAL"
    else:
        status = "DIVERGENTE"
        
    resultados.append({
        "Centro de Custo": cc,
        "Aprovador (Script Novo)": linha["Aprovador (Diretor)"],
        "Aprovador (Entrega Antiga)": linha["Aprovador"],
        "Status Comparação": status
    })

df_relatorio = pd.DataFrame(resultados)

# 5. Exportando o relatório separado em abas
print(f"Salvando o relatório de auditoria em: {arquivo_relatorio}")
with pd.ExcelWriter(arquivo_relatorio, engine="openpyxl") as writer:
    df_relatorio[df_relatorio["Status Comparação"] == "DIVERGENTE"].to_excel(writer, sheet_name="Diferenças", index=False)
    df_relatorio[df_relatorio["Status Comparação"].str.contains("NOVO CC")].to_excel(writer, sheet_name="Novos CCs", index=False)
    df_relatorio[df_relatorio["Status Comparação"] == "IGUAL"].to_excel(writer, sheet_name="Iguais", index=False)

print("\nComparação concluída com sucesso! O relatório está na pasta 'saídas'.")