from langchain_ollama import ChatOllama
from langchain.agents import AgentExecutor, create_react_agent
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from src.robot_agent.robot_tools import robot_tools
import json
import yaml
import re

# Função para limpar output do LLM
def clean_llm_output(text: str) -> str:
    """Remove caracteres unicode inválidos e texto em outros idiomas"""
    # Remove caracteres unicode não-ASCII exceto pontuação comum
    cleaned = re.sub(r'[^\x00-\x7F]+', '', text)
    # Remove tags <unused...>
    cleaned = re.sub(r'<unused\d+>', '', cleaned)
    return cleaned.strip()

# 1. Configurar a LLM Principal (Gemma3B via Ollama)
main_llm = ChatOllama(model="gemma3:4b", temperature=0.1)

# 2. Carregar o Prompt do Agente a partir do arquivo YAML
with open('Prompts/main_prompt.yaml', 'r') as file:
    agent_prompt = yaml.safe_load(file)['prompt']

# Definir o Prompt do Agente (ReAct/ZeroShotAgent)
# Este prompt guia o Gemma3B sobre como pensar e usar as ferramentas.
# Ele DEVE explicar claramente as ferramentas e o processo de pensamento esperado.
agent_prompt = PromptTemplate.from_template(agent_prompt)

# 5. Loop de Interação
if __name__ == "__main__":
    print("Robot: Hello! How can I help you today? (Type 'exit' to quit)")
    while True:
        user_input = input("You: ")
        if user_input.lower() == 'exit':
            print("Robot: Goodbye!")
            break
      
        try:
            # IMPORTANTE: Criar nova instância do executor para cada comando
            # Isso limpa o agent_scratchpad e evita contaminação de contexto
            fresh_agent = create_react_agent(main_llm, robot_tools, agent_prompt)
            fresh_executor = AgentExecutor(
                agent=fresh_agent,
                tools=robot_tools,
                verbose=False,
                handle_parsing_errors=True,
                max_iterations=15,
                return_intermediate_steps=True
            )
            
            # Invocar com executor limpo
            response = fresh_executor.invoke({"input": user_input})
            # Limpar o output antes de exibir
            cleaned_output = clean_llm_output(response['output'])
            print(f"Robot: {cleaned_output}")
        except Exception as e:
            error_message = str(e)
            # Limpar a mensagem de erro também
            cleaned_error = clean_llm_output(error_message)
            print(f"Robot: An error occurred while processing your request: {cleaned_error}")
            print("Please try again or rephrase your sentence.")
