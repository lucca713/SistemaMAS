import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import os

def plot_metrics(csv_file="metrics.csv"):
    if not os.path.isfile(csv_file):
        print(f"Erro: Arquivo '{csv_file}' não encontrado. Rode o main.py primeiro.")
        return

    # Lê os dados
    df = pd.read_csv(csv_file)

    # Verifica se o dataframe não está vazio
    if df.empty:
        print("Aviso: O arquivo CSV está vazio.")
        return

    # Criação da figura
    plt.figure(figsize=(10, 6))
    sns.set_theme(style="whitegrid")

    # Mapeando cores para o status (verde para sucesso, vermelho para falha, cinza para outros)
    palette = {"success": "green", "failed": "red"}
    
    # Adicionando cores padrão para status não previstos (ex: in_progress, unknown)
    unique_statuses = df["status"].unique()
    for status in unique_statuses:
        if status not in palette:
            palette[status] = "gray"

    # Plot do gráfico de barras (Duração por Modelo, colorido por Status)
    # Agrupamos por modelo e pegamos a média ou plotamos os pontos individuais.
    # Vamos usar um barplot padrão. Se houver múltiplas corridas por modelo, ele calcula a média com barra de erro.
    ax = sns.barplot(
        data=df, 
        x="model_name", 
        y="duration_seconds", 
        hue="status",
        palette=palette,
        capsize=.1,
        err_kws={'linewidth': 1.5}
    )

    plt.title("Comparativo de Tempo e Sucesso por Modelo LLM", fontsize=14, pad=15)
    plt.xlabel("Modelo Utilizado", fontsize=12)
    plt.ylabel("Tempo de Execução (Segundos)", fontsize=12)
    
    # Ajustando legenda
    plt.legend(title="Status da Missão", loc="upper left", bbox_to_anchor=(1, 1))

    # Rotaciona labels se os nomes dos modelos forem grandes
    plt.xticks(rotation=45)
    plt.tight_layout()

    # Salva o gráfico
    output_img = "resultado_comparativo.png"
    plt.savefig(output_img, dpi=300)
    print(f"Gráfico gerado com sucesso e salvo em: {output_img}")
    
    # Opcional: mostrar na tela (comentado caso rode em ambiente sem display/servidor remoto)
    # plt.show()

if __name__ == "__main__":
    plot_metrics()
