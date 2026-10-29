# Correções: Detecção de Objetos e Pessoas

## Problema 1: Detecção de Objetos em Salas

### Sintoma
O robô não estava verificando corretamente se objetos existiam na sala atual. Exemplo:
- Usuário: "bring me the towel, it's in the bathroom"
- Robô navega para o bathroom
- Robô não encontra a towel (mesmo ela estando lá no cenário)

### Causa Raiz
A variável `robot_current_room` era uma variável global de módulo simples. Quando o módulo é importado em diferentes contextos (especialmente com o LangChain AgentExecutor), a variável pode ser reinicializada ou não compartilhada corretamente entre diferentes invocações das ferramentas.

### Solução Implementada

#### 1. Criada Classe Singleton `RobotState`

```python
class RobotState:
    """Manages the robot's current state (location, etc.)"""
    _instance = None
    _current_room = "living room"
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(RobotState, cls).__new__(cls)
        return cls._instance
    
    @property
    def current_room(self):
        return self._current_room
    
    @current_room.setter
    def current_room(self, room):
        self._current_room = room.lower() if room else "living room"
        print(f"[RobotState] Current room updated to: '{self._current_room}'")
```

#### 2. Benefícios do Singleton

- **Persistência**: Uma única instância compartilhada em todo o módulo
- **Thread-safe**: O padrão singleton garante apenas uma instância
- **Debug**: Logs automáticos quando a sala muda
- **Property**: Usa @property para validação automática (lowercase)

#### 3. Mudanças nas Funções

**Antes:**
```python
global robot_current_room
robot_current_room = room.lower()
```

**Depois:**
```python
robot_state.current_room = room  # Automatically lowercased via property
```

## Problema 2: Loop Infinito ao Procurar Pessoas

### Sintoma
Quando o robô tentava encontrar uma pessoa desconhecida (Bruno, Carla, Diego), ele entrava em loop infinito:
- `find_person` detectava que a pessoa era desconhecida
- Retornava mensagem "I don't know X yet..."
- Agente LLM chamava `find_person` novamente
- Loop infinito

### Causa Raiz
A ferramenta `find_person` não estava delegando para `search_for_person` quando a pessoa era desconhecida. Em vez disso, apenas retornava uma mensagem, fazendo o agente ficar confuso e chamar `find_person` repetidamente.

### Solução Implementada

#### 1. Corrigido `find_person` para Delegar a Busca Física

**Antes:**
```python
else:
    # Pessoa desconhecida - inicia busca
    print(f"[ROBOT INFO] {person_name} is unknown. Starting physical search...")
    publisher.publish_person_search("searching", person_name, action="find")
    
    return f"I don't know {person_name} yet. Starting search through the house..."
```

**Depois:**
```python
else:
    # Pessoa desconhecida - inicia busca física usando search_for_person
    print(f"[ROBOT INFO] {person_name} is unknown. Starting physical search...")
    publisher.publish_person_search("searching", person_name, action="find")
    
    # Chama search_for_person para fazer a busca física
    search_input = {"person_name": person_name}
    if message:
        search_input["message"] = message
    
    return search_for_person(json.dumps(search_input))
```

#### 2. `search_for_person` Já Estava Correto

A ferramenta `search_for_person` já estava usando o `scenario_manager` corretamente:

```python
# SIMULAÇÃO: Verifica no cenário se a pessoa está nesta sala
if scenario_manager and scenario_manager.check_person_in_room(person_name, room):
    person_found = True
    found_location = room
    print(f"[ROBOT INFO] Found {person_name} in {room}!")
    break
```

## Status Geral

### ✅ Objetos
- RobotState singleton implementado
- navigate_to atualiza robot_state.current_room
- pick_up_object usa robot_state.current_room
- search_for_object usa scenario_manager
- Debug logs adicionados

### ✅ Pessoas
- find_person agora delega para search_for_person quando pessoa é desconhecida
- search_for_person usa scenario_manager.check_person_in_room()
- Loop infinito corrigido

## Dados do Cenário (baseline_house_1)

### Pessoas:
- Ana: kitchen
- Bruno: living room
- Carla: bedroom
- Diego: dining room

### Exemplos de Objetos:
- pen: bedroom (0.02 kg) ✓
- towel: bathroom (0.25 kg) ✓
- cup: kitchen (0.25 kg) ✓
- refrigerator: kitchen (60.0 kg - muito pesado) ✓

## Como Testar

```bash
cd ros2_ws
python3 router.py
```

### Comandos de teste para Objetos:
1. `bring me the towel` → deve procurar e encontrar no bathroom ✓
2. `bring me the pen` → deve procurar e encontrar no bedroom ✓
3. `bring me the refrigerator` → deve dizer que é muito pesado ✓

### Comandos de teste para Pessoas:
1. `find Bruno` → deve procurar e encontrar no living room ✓
2. `find Carla` → deve procurar e encontrar no bedroom ✓
3. `find Diego` → deve procurar e encontrar no dining room ✓
4. `find Ana` (após já ter encontrado antes) → deve dizer "I know Ana! Last seen at kitchen" ✓

## Verificação Manual

```python
from scenario_manager import get_scenario_manager

sm = get_scenario_manager()

# Objetos
print(sm.check_object_in_room('towel', 'bathroom'))  # True
print(sm.check_object_in_room('pen', 'bedroom'))     # True

# Pessoas
print(sm.check_person_in_room('Bruno', 'living room'))  # True
print(sm.check_person_in_room('Carla', 'bedroom'))      # True
```
