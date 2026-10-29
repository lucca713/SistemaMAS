# Sistema de Cenários - Arquitetura

## Visão Geral

O sistema de cenários foi criado para evitar aleatoriedade nas respostas do robô sobre pessoas e objetos, permitindo uma simulação controlada e realista da casa.

## Arquitetura

### 1. **house_structure.yaml** (Conhecimento Estrutural)
- **Localização**: `ros2_ws/house_structure.yaml`
- **Propósito**: Define a estrutura estática da casa que o agente conhece
- **Conteúdo**:
  - Lista de cômodos (rooms)
  - Objetos típicos por cômodo (conhecimento genérico)
  - Restrições físicas (peso máximo que pode levantar, áreas restritas)
- **Acesso**: O agente LLM pode ler este arquivo (conhecimento estrutural)

### 2. **Cenários JSON** (Estado Atual do Mundo)
- **Localização**: `Scenarios/*.json`
- **Propósito**: Define o "gabarito" - onde pessoas e objetos realmente estão
- **Conteúdo**:
  - Lista de pessoas (nome + localização)
  - Lista de objetos (tipo + localização + peso)
- **Acesso**: O agente LLM **NUNCA** acessa diretamente (evita trapaça)

### 3. **scenario_manager.py** (Simulador de Sensores)
- **Localização**: `ros2_ws/scenario_manager.py`
- **Propósito**: Faz a ponte entre o cenário e o agente, simulando sensores
- **Métodos principais**:
  - `check_person_in_room(person, room)`: Simula "pessoa está nesta sala?"
  - `get_objects_in_room(room)`: Simula "que objetos vejo aqui?"
  - `can_lift_object(object, room)`: Verifica se pode levantar (peso)
- **Acesso**: Usado internamente pelas ferramentas (tools) do robô

### 4. **robot_tools.py** (Ferramentas do Agente)
- **Localização**: `ros2_ws/src/robot_agent/robot_tools.py`
- **Mudanças**: Ferramentas agora usam `scenario_manager` ao invés de aleatoriedade
- **Exemplo**: `search_for_person` agora verifica no cenário se a pessoa está na sala

## Fluxo de Funcionamento

```
Usuário: "Find Ana"
    ↓
Agente LLM (não sabe onde Ana está)
    ↓
Tool: search_for_person("Ana")
    ↓
Itera pelas salas conhecidas (do house_structure.yaml)
    ↓
Para cada sala: scenario_manager.check_person_in_room("Ana", sala)
    ↓
Quando encontra: "Found Ana in kitchen!"
    ↓
Agente LLM memoriza: Ana está na kitchen
```

## Benefícios

1. **Consistência**: Ana sempre estará na kitchen neste cenário
2. **Realismo**: Robô deve navegar e descobrir (não sabe de antemão)
3. **Testabilidade**: Cenários controlados facilitam testes
4. **Separação de Responsabilidades**:
   - Agente: raciocínio e decisões
   - Cenário: verdade do mundo
   - Simulador: ponte entre os dois

## Próximos Passos

- [ ] Adicionar suporte para objetos com peso (Deus Ex Machina)
- [ ] Suporte para áreas restritas/portas trancadas
- [ ] Cenário dinâmico (objetos podem se mover quando o robô os pega)
- [ ] Múltiplos cenários para testes variados
