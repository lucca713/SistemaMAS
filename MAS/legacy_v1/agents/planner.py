from langchain_ollama import ChatOllama
from src.core.state import AgentState

def plan_node(state: AgentState) -> dict:
    """
    Agente de Planejamento:
    Recebe o estado com a intenção do usuário ou um feedback de falha,
    e gera um plano de passos para ser executado.
    """
    print("--- [Planejador] Trabalhando... ---")
    
    intent = state.get("user_intent")
    history = state.get("history", [])
    
    # Inicializando o LLM do Ollama
    llm = ChatOllama(model="llama3.1", temperature=0)
    
    prompt = f"""
    Você é o Agente de Planejamento de um robô de serviço doméstico.
    A intenção do usuário é: "{intent}"
    Histórico recente: {history}
    Contexto de Erro (se houver): {state.get('error_context', 'Nenhum')}
    
    Decomponha essa tarefa em uma lista de subtarefas lógicas sequenciais.
    Regra MÁXIMA: Seja EXTREMAMENTE conciso. Use o MÍNIMO de passos possíveis.
    
    DIRETRIZES DE NAVEGAÇÃO:
    1. Se a intenção for apenas "ir" a um lugar e não houver erro, gere APENAS UM passo: "ir até o [destino]".
    2. Se houver um 'Contexto de Erro' indicando que o caminho está bloqueado (Falha), você DEVE assumir o controle manual para tirar o robô de lá.
       Nesse caso, GERE APENAS OS PASSOS DE MANOBRA e depois tente ir ao destino novamente. NÃO repita a ação que falhou no início do plano!
       Exemplo CORRETO de plano de fuga: ["dar ré", "girar para a direita", "ir até o [destino]"]
       Exemplo ERRADO: ["ir até o bloco", "dar ré"] (Nunca comece com a ação que acabou de falhar).
       
    Responda APENAS com a lista de passos separados por vírgula.
    """
    
    response = llm.invoke(prompt)
    
    # Processando a resposta do LLM para criar uma lista
    content = response.content
    if isinstance(content, list):
        plan_text = content[0].get("text", "") if isinstance(content[0], dict) else str(content[0])
    else:
        plan_text = str(content)
        
    plan_text = plan_text.strip()
    plan_list = [step.strip() for step in plan_text.split(',')]
    
    print(f"--- [Planejador] Novo Plano Gerado: {plan_list} ---")
    
    return {"current_plan": plan_list}
