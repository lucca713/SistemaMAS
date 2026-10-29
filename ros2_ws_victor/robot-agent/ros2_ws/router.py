from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate
from langchain.agents import AgentExecutor, create_react_agent
import yaml
import json
import re

# Importar ferramentas e funções necessárias
from main_robot_agent import clean_llm_output
from conversation_agent import process_conversation
from src.robot_agent.robot_tools import robot_tools

# Importar RAG pipeline diretamente
from rag_pipeline import get_context, search_with_filter

# Configurar a LLM para o router
router_llm = ChatOllama(model="gemma3:4b", temperature=0.3)

# Configurar a LLM para comandos (igual ao main_robot_agent)
command_llm = ChatOllama(model="gemma3:4b", temperature=0.1)

# Carregar o prompt do agente de comando
with open('Prompts/main_prompt.yaml', 'r') as file:
    command_agent_prompt_text = yaml.safe_load(file)['prompt']

command_agent_prompt = PromptTemplate.from_template(command_agent_prompt_text)

# Carregar o prompt do router
with open('Prompts/router_prompt.yaml', 'r') as file:
    router_prompt = yaml.safe_load(file)['prompt']

# Criar o prompt template
router_prompt_template = PromptTemplate.from_template(router_prompt)

# Prompt para respostas com contexto RAG
rag_response_prompt = """You are a helpful household assistant robot with access to comprehensive robotics documentation.

Based on the following context from my knowledge base, please answer the user's question in a helpful and informative way:

Context:
{context}

User question: {question}

Provide a clear, accurate answer based on the context. If the context doesn't fully answer the question, mention what information is available and offer to help with related topics.

Robot response:"""

rag_prompt_template = PromptTemplate.from_template(rag_response_prompt)

def is_robotics_question(user_input: str) -> bool:
    """
    Detecta se a pergunta é sobre robótica/competição/regras
    NÃO deve detectar perguntas sobre as capacidades do próprio robô
    """
    # Perguntas sobre capacidades do próprio robô (não são perguntas sobre robótica)
    self_capability_patterns = [
        'what can you do', 'what are you able to', 'can you find', 'can you pick',
        'can you navigate', 'can you deliver', 'can you help', 'are you able to',
        'what are your capabilities', 'what do you know how to do'
    ]
    
    user_lower = user_input.lower()
    
    # Se é pergunta sobre capacidades do próprio robô, NÃO é pergunta de robótica
    if any(pattern in user_lower for pattern in self_capability_patterns):
        return False
    
    robotics_keywords = [
        'robocup', 'arena', 'competition', 'task', 'rule', 'regulation',
        'navigation', 'manipulation', 'scoring', 'configuration', 'minimal', 
        'maximum', 'specification', 'requirement', 'procedure', 'guideline',
        'safety', 'allowed', 'not allowed', 'points', 'penalty', 'bonus',
        'home', 'league', 'team', 'judge', 'referee', 'technical'
    ]
    
    return any(keyword in user_lower for keyword in robotics_keywords)

def answer_robotics_question(user_input: str) -> str:
    """
    Responde perguntas sobre robótica usando o RAG
    """
    try:
        # Buscar contexto relevante
        context = get_context(user_input, k=3)
        
        if context and context != "Nenhum contexto relevante encontrado.":
            # Usar LLM para formular resposta com contexto
            response = router_llm.invoke(
                rag_prompt_template.format(context=context, question=user_input)
            )
            return response.content
        else:
            # Se não encontrou contexto, tentar busca alternativa
            alt_context = search_with_filter(user_input, {"tipo": "rulebook"}, k=2)
            if alt_context and alt_context != "Nenhum contexto relevante encontrado.":
                response = router_llm.invoke(
                    rag_prompt_template.format(context=alt_context, question=user_input)
                )
                return response.content
            else:
                return "I don't have specific information about that in my knowledge base. Could you rephrase your question or ask about competition rules, robot tasks, arena configuration, or procedures?"
                
    except Exception as e:
        return f"Sorry, I encountered an error while searching my knowledge base: {e}"

# Função para determinar o tipo de input
def determine_input_type(user_input: str) -> str:
    """
    Determine if the user input is a command or a conversation.
    Return 'command' or 'conversation'.
    """
    try:
        # Usar a LLM para interpretar o input
        response = router_llm.invoke(
            router_prompt_template.format(input=user_input)
        )
        
        # Tentar extrair o JSON da resposta
        content = response.content
        # Procura por um padrão JSON na resposta
        json_match = re.search(r'\{.*\}', content)
        if json_match:
            try:
                result = json.loads(json_match.group())
                return result.get('type', 'conversation')
            except json.JSONDecodeError:
                pass
        
        # Se não conseguir parsear como JSON, verifica o contexto da frase
        input_lower = user_input.lower()
        
        # Detecta perguntas sobre localização de pessoas (comandos disfarçados)
        person_location_patterns = [
            'where is', 'do you know where', 'have you seen', 'where\'s',
            'find', 'look for', 'search for', 'locate'
        ]
        if any(pattern in input_lower for pattern in person_location_patterns):
            # Verifica se não é uma pergunta sobre objetos/lugares/robótica
            if not any(word in input_lower for word in ['object', 'room', 'kitchen', 'bedroom', 'bathroom', 'rule', 'regulation']):
                return 'command'
        
        # Palavras que indicam uma solicitação de informação ou ajuda
        info_words = ['help', 'explain', 'what', 'how', 'why', 'when', 'can you', 'could you', 'would you']
        if any(word in input_lower for word in info_words):
            # Mas se inclui "where", pode ser sobre pessoa
            if 'where' not in input_lower:
                return 'conversation'
            
        # Palavras que indicam um comando físico
        command_words = ['pick up', 'go to', 'bring', 'take', 'move', 'get', 'deliver']
        if any(word in input_lower for word in command_words):
            # Verifica se é um comando físico real ou uma metáfora/conversação
            if any(word in input_lower for word in ['help me', 'explain', 'understand', 'learn', 'teach']):
                return 'conversation'
            return 'command'
            
        return 'conversation'
            
    except Exception as e:
        # Se houver erro, assume que é uma conversação
        return 'conversation'

# Função principal do router
def route_input(user_input: str) -> str:
    """
    Route the input to the appropriate agent.
    """
    # Primeiro, verificar se é uma pergunta sobre robótica
    if is_robotics_question(user_input):
        return answer_robotics_question(user_input)
    
    # Se não é sobre robótica, determinar se é comando ou conversação
    input_type = determine_input_type(user_input)
    
    if input_type == 'command':
        try:
            # Criar fresh agent para evitar contaminação de contexto
            fresh_agent = create_react_agent(command_llm, robot_tools, command_agent_prompt)
            fresh_executor = AgentExecutor(
                agent=fresh_agent,
                tools=robot_tools,
                verbose=False,
                handle_parsing_errors=True,
                max_iterations=15,
                return_intermediate_steps=True
            )
            
            # Usar o agente de comandos com executor limpo
            response = fresh_executor.invoke({"input": user_input})
            # Limpar o output antes de retornar
            return clean_llm_output(response['output'])
        except Exception as e:
            # Se falhar, tentar novamente com input reformulado
            error_str = str(e)
            if "early_stopping_method" in error_str:
                print("[DEBUG] Detected early_stopping_method error, attempting recovery...")
                # Informar o usuário sobre o problema técnico
                return "I apologize, but I encountered a technical issue. Could you please rephrase your command?"
            # Limpar a mensagem de erro
            cleaned_error = clean_llm_output(error_str)
            raise Exception(cleaned_error)
    else:
        # Usar o novo agente de conversação
        response = process_conversation(user_input)
        
        # Se a resposta indica que é um comando, verifica novamente o contexto
        if response == "__COMMAND_MODE__":
            # Verifica se é realmente um comando físico ou uma metáfora/conversação
            if any(word in user_input.lower() for word in ['help me', 'explain', 'understand', 'learn', 'teach']):
                return "I apologize, but I am a household assistant robot. I can help you with physical tasks like picking up objects, navigating rooms, and delivering items. I cannot help with academic subjects or explanations."
            try:
                # Criar fresh agent para evitar contaminação de contexto
                fresh_agent = create_react_agent(command_llm, robot_tools, command_agent_prompt)
                fresh_executor = AgentExecutor(
                    agent=fresh_agent,
                    tools=robot_tools,
                    verbose=False,
                    handle_parsing_errors=True,
                    max_iterations=15,
                    return_intermediate_steps=True
                )
                
                command_response = fresh_executor.invoke({"input": user_input})
                return clean_llm_output(command_response['output'])
            except Exception as e:
                error_str = str(e)
                if "early_stopping_method" in error_str:
                    return "I apologize, but I encountered a technical issue. Could you please rephrase your command?"
                cleaned_error = clean_llm_output(error_str)
                raise Exception(cleaned_error)
            
        return response

# Loop principal de interação
if __name__ == "__main__":
    print("Robot: Hello! I'm your household assistant robot. How can I help you today? (Type 'exit' to quit)")
    while True:
        user_input = input("You: ")
        if user_input.lower() == 'exit':
            print("Robot: Goodbye!")
            break
        
        try:
            response = route_input(user_input)
            # Limpar o output final antes de exibir
            cleaned_response = clean_llm_output(response)
            print(f"Robot: {cleaned_response}")
        except Exception as e:
            error_message = str(e)
            cleaned_error = clean_llm_output(error_message)
            print(f"Robot: An error occurred while processing your request: {cleaned_error}")
            print("Please try again or rephrase your sentence.")
