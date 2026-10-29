import os
import xml.etree.ElementTree as ET
from prompt import classify_sentence
from XML_Generator import create_annotated_xml

# Caminhos
dataset_path = "../Datasets/huric-master/en/Simpleset"
output_path = "./output"

# Cria a pasta de saída se não existir
os.makedirs(output_path, exist_ok=True)

# Iterar sobre todos os arquivos .hrc
for filename in os.listdir(dataset_path):
    if filename.endswith(".hrc"):
        file_path = os.path.join(dataset_path, filename)
        tree = ET.parse(file_path)
        root = tree.getroot()
        
        # Extrair a sentença (assumindo estrutura padrão do .hrc)
        sentence_elem = root.find(".//sentence")
        if sentence_elem is not None:
            sentence = sentence_elem.text.strip()
            print(f"Classificando: {filename} - \"{sentence}\"")
            
            # Chama o classificador do prompt.py (usa Ollama com Gemma)
            word_labels = classify_sentence(sentence)

            # Gerar XML anotado
            sentence_id = int(filename.replace(".hrc", ""))
            annotated_xml = create_annotated_xml(sentence_id, eval(word_labels))  # transforma string em lista

            # Salvar arquivo
            with open(os.path.join(output_path, f"{sentence_id}.xml"), "w") as f:
                f.write(annotated_xml)
