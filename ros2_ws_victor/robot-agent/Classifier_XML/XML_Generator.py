import xml.etree.ElementTree as ET
from xml.dom import minidom

def create_annotated_xml(sentence_id, word_labels):
    root = ET.Element("huricExample", attrib={"id": str(sentence_id)})

    # Comando original
    commands = ET.SubElement(root, "commands")
    command = ET.SubElement(commands, "command")
    sentence_text = " ".join([w for w, _ in word_labels])
    ET.SubElement(command, "sentence").text = sentence_text

    # Tokens anotados
    tokens_el = ET.SubElement(command, "tokens")
    for i, (word, label) in enumerate(word_labels, start=1):
        ET.SubElement(tokens_el, "token", {
            "id": str(i),
            "surface": word,
            "label": label
        })

    # Formatar como XML bonito
    xml_str = ET.tostring(root, encoding="utf-8")
    pretty_xml = minidom.parseString(xml_str).toprettyxml(indent="  ")
    return pretty_xml

# Exemplo com a saída que você obteve do Gemma3
example_output = [
    ("bring", "action"),
    ("the", "other"),
    ("apple", "object"),
    ("near", "direction"),
    ("the", "other"),
    ("shelf", "location"),
    ("in", "other"),
    ("the", "other"),
    ("kitchen", "room")
]

# Gerar XML e salvar
xml_result = create_annotated_xml(sentence_id=1, word_labels=example_output)

with open("classified_sentence_001.xml", "w") as f:
    f.write(xml_result)

print("Arquivo XML gerado com sucesso.")
