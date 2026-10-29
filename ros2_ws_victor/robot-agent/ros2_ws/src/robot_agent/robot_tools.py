# imports para ROS2
import rclpy
from rclpy.node import Node
from std_msgs.msg import String

import requests
from langchain.tools import tool
import json
import yaml
import time

# Importando o parser JSON que o LangChain usa internamente para ser mais robusto
# from langchain.output_parsers import json as json_parser_lc # Importa o módulo json do langchain.output_parsers

# Import do RAG pipeline
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from rag_pipeline import get_context, search_with_filter

# Import do Scenario Manager
from scenario_manager import get_scenario_manager

# Classe para o publisher ROS2
class RobotPublisher(Node):
    def __init__(self):
        super().__init__('robot_publisher')
        self.room_publisher = self.create_publisher(String, 'room', 10)
        self.person_search_publisher = self.create_publisher(String, 'person_search', 10)
        self.object_publisher = self.create_publisher(String, 'object', 10)
        self.get_logger().info('Robot Publisher initialized')

    def publish_room(self, room_name):
        msg = String()
        msg.data = room_name
        self.room_publisher.publish(msg)
        self.get_logger().info(f'Published room: {room_name}')
    
    def publish_person_search(self, status, person, **kwargs):
        """
        Publica informações sobre a busca de pessoas no tópico person_search.
        
        Args:
            status: Estado da busca ('searching', 'found', 'not_found')
            person: Nome da pessoa sendo procurada
            **kwargs: Argumentos adicionais (ex: current_room, location, rooms_searched, message)
        """
        msg = String()
        data = {"status": status, "person": person, **kwargs}
        msg.data = json.dumps(data)
        self.person_search_publisher.publish(msg)
        self.get_logger().info(f'Published person_search: {msg.data}')
    
    def publish_object(self, object_name):
        """
        Publica o nome do objeto encontrado no tópico object.
        
        Args:
            object_name: Nome do objeto encontrado
        """
        msg = String()
        msg.data = object_name
        self.object_publisher.publish(msg)
        self.get_logger().info(f'Published object: {object_name}')

# Variável global para o nó ROS2
robot_publisher_node = None

def init_ros_node():
    """Inicializa o nó ROS2 se ainda não foi inicializado"""
    global robot_publisher_node
    if robot_publisher_node is None:
        if not rclpy.ok():
            rclpy.init()
        robot_publisher_node = RobotPublisher()
    return robot_publisher_node

# Initialize scenario manager (for simulation)
try:
    scenario_manager = get_scenario_manager()
    print(f"[ScenarioManager] Initialized with scenario: {scenario_manager.get_scenario_name()}")
except Exception as e:
    print(f"[ScenarioManager] Warning: Could not initialize scenario manager: {e}")
    scenario_manager = None

# Robot state management (singleton pattern for persistence)
class RobotState:
    """Manages the robot's current state (location, etc.)"""
    _instance = None
    _current_room = "living room"  # Default starting room
    
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

# Global robot state instance
robot_state = RobotState()

def normalize_room_name(room: str) -> str:
    """
    Normaliza nomes de sala para garantir que 'dining room' nunca seja interpretado como 'dining' sozinho.
    """
    room = room.lower().strip()
    if room == "dining":
        return "dining room"

    if room == "hallway":
        return "hall"
    return room

# Carregar o prompt do classificador a partir do arquivo YAML
try:
    with open('Prompts/classifier_prompt.yaml', 'r') as file:
        CLASSIFIER_PROMPT = yaml.safe_load(file)['prompt']
except (FileNotFoundError, KeyError) as e:
    print(f"Warning: classifier_prompt.yaml not found ({e}), using default prompt")
    CLASSIFIER_PROMPT = "Classify the following sentence into semantic categories (action, object, location, room, direction, other). Return as Python list of tuples."

known_objects = ["cup", "mug", "bowl", "dish", "spoon", "fork", "knife", "napkin", "tray", "basket", "trash bag", "book", "CD", "DVD", "BluRay", "cereal box", "milk carton", "bag", "coat", "apple", "paper", "teabag", "pen", "remote control", "chocolate egg", "refrigerator bottle", "newspaper", "umbrella"]
known_rooms = ["bedroom", "kitchen", "living room", "dining room", "bathroom", "hall", "laundry room", "garage"]
known_people = []  # Lista de pessoas conhecidas com formato: {"name": str, "last_location": str, "timestamp": str}

@tool
def classify_sentence_semantic(sentence: str) -> str:
    """
    Classifies each word of a sentence into semantic categories (action, object, location, room, direction, other)
    using Gemma3B via Ollama. Returns a JSON string of a dictionary summarizing the semantic tokens.
    """
    system_prompt_with_sentence = CLASSIFIER_PROMPT + f"\nSentence: {sentence}\nOutput:"
    try:
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": "gemma3:4b",
                "prompt": system_prompt_with_sentence,
                "stream": False,
                "options": {"temperature": 0.0} # Importante para classificação consistente
            }
        )
        response.raise_for_status() # Lança um HTTPError para respostas ruins (4xx ou 5xx)
        gemma_output_str = response.json()["response"].strip()

        # Tenta analisar a saída string em uma lista de tuplas Python
        try:
            parsed_output = eval(gemma_output_str)
            if not isinstance(parsed_output, list) or not all(isinstance(item, tuple) and len(item) == 2 for item in parsed_output):
                raise ValueError("Parsed output is not in the expected list of (word, label) format.")
        except (SyntaxError, ValueError) as e:
            return f"Error parsing Gemma3 output: {e}. Raw output: {gemma_output_str}"

        # Converte a lista de (word, label) em um dicionário resumido para consumo mais fácil pela LLM principal
        semantic_dict = {}
        for word, label in parsed_output:
            if label != "other": # Ignora "other"
                # Lida com casos onde um rótulo pode aparecer várias vezes (por exemplo, múltiplos objetos)
                if label in semantic_dict:
                    if not isinstance(semantic_dict[label], list):
                        semantic_dict[label] = [semantic_dict[label]]
                    semantic_dict[label].append(word)
                else:
                    semantic_dict[label] = word
        
        return json.dumps(semantic_dict)
        
    except requests.exceptions.RequestException as e:
        return f"Error calling Ollama: {e}"
    
@tool
def rewrite_sentence(input_str: str) -> str:
    """
    Rewrite the sentence command with more information that you get from ask_user tool.
    Use your own knowledge to rewrite the sentence

    Here is an example:
    [User] "Take the keys"
    [Robot] used ask_user tool and get new informations about where the keys are.
    [User] "They are on the kitchen table"
    [Robot] Add the new informations to the sentence like this: "Take the keys from the kitchen table"
    [Robot] Return the new sentence: "Take the keys from the kitchen table"
    [Robot] Restart his workflow with the new sentence using the `classify_sentence_semantic` tool

    """
    try:
        # Tenta remover as aspas simples externas se existirem
        if input_str.startswith("'") and input_str.endswith("'"):
            input_str = input_str[1:-1]
        
        # Tenta analisar como JSON primeiro
        try:
            parsed_input = json.loads(input_str)
            # Se for JSON, retorna o texto formatado
            return f"Rewritten sentence: {input_str}"
        except json.JSONDecodeError:
            # Se não for JSON, trata como string normal
            return f"Rewritten sentence: {input_str}"
            
    except Exception as e:
        return f"An unexpected error occurred in rewrite_sentence: {e}"

@tool
def navigate_to(input_str: str) -> str:
    """
    Navigates the robot to a specified room in the house.
    Returns a confirmation message or an error.
    The input should be a JSON string with a 'room' key, for example: '{"room": "kitchen"}'.
    """
    try:
        # Inicializa o nó ROS2 se necessário
        publisher = init_ros_node()

        # Tenta remover as aspas simples externas se existirem
        if input_str.startswith("'") and input_str.endswith("'"):
            input_str = input_str[1:-1]
        
        parsed_input = json.loads(input_str)
        room = normalize_room_name(parsed_input.get("room"))
        if not room:
            return "Error: 'room' key not found in input JSON for navigate_to."
        
        print(f"[ROBOT ACTION] Navigating to room: {room}")

        # Publica no tópico ROS2
        publisher.publish_room(room)
        
        # Update robot's current location using singleton
        robot_state.current_room = room
        
        # Simula a chamada à API de navegação do robô
        if room.lower() in known_rooms:
            return f"Robot arrived at {room}."
        else:
            # adiciona um novo cômodo a lista de cômodos conhecidos
            known_rooms.append(room)
            print(f"Room '{room}' added to known_rooms list.")
            return f"Robot arrived at {room}."
        
        '''
        else:
            return f"Cannot navigate to '{room}'. Unknown or inaccessible room."
        '''
    except json.JSONDecodeError:
        return f"Error: Invalid JSON input for navigate_to. Ensure it uses double quotes: {input_str}"
    except Exception as e:
        return f"An unexpected error occurred in navigate_to: {e}"

@tool
def move_robot(input_str: str) -> str:
    """
    Movimenta o robô manualmente no espaço físico (Controle Remoto).
    The input should be a JSON string with a 'direction' key ('forward', 'backward', 'left', 'right').
    Example: '{"direction": "backward"}'
    """
    try:
        if input_str.startswith("'") and input_str.endswith("'"):
            input_str = input_str[1:-1]
        
        parsed_input = json.loads(input_str)
        direction = parsed_input.get("direction")
        if not direction:
            return "Error: 'direction' key not found in input JSON for move_robot."
            
        print(f"[ROBOT ACTION] Manual override: Moving {direction}")
        
        from geometry_msgs.msg import Twist
        import time
        import rclpy
        from rclpy.node import Node
        
        # Cria um nó temporário para publicar a velocidade
        temp_node = Node('temp_manual_driver')
        pub = temp_node.create_publisher(Twist, '/cmd_vel', 10)
        
        msg = Twist()
        if direction == 'forward':
            msg.linear.x = 0.3
        elif direction == 'backward':
            msg.linear.x = -0.3
        elif direction == 'left':
            msg.angular.z = 0.5
        elif direction == 'right':
            msg.angular.z = -0.5
        else:
            return f"Error: unknown direction {direction}"
            
        # Publica o comando de movimento por 2.5 segundos
        start = time.time()
        while time.time() - start < 2.5:
            pub.publish(msg)
            time.sleep(0.1)
            
        # Para o robô
        msg.linear.x = 0.0
        msg.angular.z = 0.0
        pub.publish(msg)
        time.sleep(0.1)
        pub.publish(msg) # Publica duas vezes para garantir
        
        temp_node.destroy_node()
        return f"Action completed: Moved {direction} successfully."
        
    except json.JSONDecodeError:
        return f"Error: Invalid JSON input for move_robot. Ensure it uses double quotes: {input_str}"
    except Exception as e:
        return f"An unexpected error occurred in move_robot: {e}"

@tool
def pick_up_object(input_str: str) -> str:
    """
    Attempts to pick up a specific object in the robot's current room.
    The robot must navigate to the room where the object is located first.
    Returns a success or failure message.
    The input should be a JSON string with an 'object_name' key, for example: '{"object_name": "box"}'.
    """
    try:
        # Tenta remover as aspas simples externas se existirem
        if input_str.startswith("'") and input_str.endswith("'"):
            input_str = input_str[1:-1]
        
        parsed_input = json.loads(input_str)
        object_name = parsed_input.get("object_name")
        if not object_name:
            return "Error: 'object_name' key not found in input JSON for pick_up_object."

        print(f"[ROBOT ACTION] Attempting to pick up: {object_name}")
        
        # SIMULATION: Check if object exists in current room using scenario_manager
        if scenario_manager:
            # Debug: Print current room
            current_room = robot_state.current_room
            print(f"[DEBUG] Current room: '{current_room}'")
            print(f"[DEBUG] Looking for object: '{object_name}'")
            
            # Check if object is in current room
            object_in_room = scenario_manager.check_object_in_room(object_name, current_room)
            print(f"[DEBUG] Object in room check result: {object_in_room}")
            
            if object_in_room:
                # Inicializa o nó ROS2 se necessário
                publisher = init_ros_node()
                
                # Publica o objeto encontrado no tópico 'object'
                publisher.publish_object(object_name)
                
                # Check if robot can lift it (weight constraint)
                weight = scenario_manager.get_object_weight(object_name, current_room)
                max_weight = 3.0  # Robot's maximum lifting capacity
                can_lift = weight and weight <= max_weight
                
                print(f"[DEBUG] Object weight: {weight} kg, Can lift: {can_lift}")
                
                if not can_lift:
                    # Object is too heavy - return to Living Room before reporting failure
                    print(f"[ROBOT ACTION] Object too heavy. Returning to Living Room (home base)...")
                    navigate_to(json.dumps({"room": "living room"}))
                    return f"I cannot carry the {object_name} from the {current_room}. It is too heavy for me. I can only carry objects up to {max_weight} kg maximum."
                
                # Successfully picked up
                if object_name.lower() not in [obj.lower() for obj in known_objects]:
                    known_objects.append(object_name)
                    print(f"Object '{object_name}' added to known_objects list.")
                
                return f"Object '{object_name}' picked up successfully."
            else:
                # Object not in current room - return to Living Room before asking for help
                print(f"[ROBOT ACTION] Object not found in current room. Returning to Living Room (home base)...")
                navigate_to(json.dumps({"room": "living room"}))
                return f"I don't see '{object_name}' in the {current_room}. Could you tell me which room it's in?"
        else:
            # Fallback if scenario_manager is not available (should not happen in normal use)
            if object_name.lower() in known_objects:
                return f"Object '{object_name}' picked up successfully."
            else:
                known_objects.append(object_name)
                print(f"Object '{object_name}' added to known_objects list.")
                return f"Object '{object_name}' picked up successfully."

        '''
        else:
            return f"Could not find or pick up the object '{object_name}'."
        '''

    except json.JSONDecodeError:
        return f"Error: Invalid JSON input for pick_up_object. Ensure it uses double quotes: {input_str}"
    except Exception as e:
        return f"An unexpected error occurred in pick_up_object: {e}"

@tool
def search_for_object(input_str: str) -> str:
    """
    Physically searches for an object by navigating through rooms in the house.
    Use this when the user asks to find or bring an object but doesn't specify where it is.
    Navegate trough all the rooms in the house looking for the object, verify if the object is in the rooms, one by one.
    The robot will systematically search rooms until it finds the object.
    
    Input should be a JSON string with 'object_name' key, for example:
    '{"object_name": "pen"}'
    
    Returns the location where the object was found, or a message if not found.
    """
    try:
        # Parse input
        if input_str.startswith("'") and input_str.endswith("'"):
            input_str = input_str[1:-1]
        
        parsed_input = json.loads(input_str)
        object_name = parsed_input.get("object_name")
        
        if not object_name:
            return "Error: 'object_name' key is required in input JSON for search_for_object."
        
        print(f"[ROBOT ACTION] Starting search for '{object_name}'...")
        
        rooms_searched = []
        object_found = False
        found_location = None
        
        # Search through all known rooms
        for room in known_rooms:
            print(f"[ROBOT ACTION] Searching for '{object_name}' in {room}...")
            
            # Navigate to the room
            navigate_to(json.dumps({"room": room}))
            rooms_searched.append(room)
            
            # Simulate search time
            time.sleep(0.3)
            
            # SIMULATION: Check if object is in this room
            if scenario_manager and scenario_manager.check_object_in_room(object_name, room):
                object_found = True
                found_location = room
                print(f"[ROBOT INFO] Found '{object_name}' in {room}!")
                
                # Publica o objeto encontrado no tópico 'object'
                publisher = init_ros_node()
                publisher.publish_object(object_name)
                
                break
        
        # Result of the search
        if object_found:
            # Check if robot can lift it
            if scenario_manager:
                weight = scenario_manager.get_object_weight(object_name, found_location)
                max_weight = 3.0
                
                if weight and weight > max_weight:
                    # Object is too heavy - return to Living Room before reporting failure
                    print(f"[ROBOT ACTION] Object too heavy. Returning to Living Room (home base)...")
                    navigate_to(json.dumps({"room": "living room"}))
                    return f"I found the {object_name} in the {found_location}, but I cannot carry it. It is too heavy for me. I can only carry objects up to {max_weight} kg maximum."
            
            return f"Found '{object_name}' in the {found_location}! I'm currently at the {found_location}."
        else:
            # Object not found after searching all rooms - return to Living Room
            print(f"[ROBOT ACTION] Object not found. Returning to Living Room (home base)...")
            navigate_to(json.dumps({"room": "living room"}))
            return f"I searched {len(rooms_searched)} rooms but couldn't find '{object_name}'. Could you tell me which room it's in, or if it might be called by a different name?"
        
    except json.JSONDecodeError:
        return f"Error: Invalid JSON input for search_for_object. Ensure it uses double quotes: {input_str}"
    except Exception as e:
        return f"An unexpected error occurred in search_for_object: {e}"

@tool
def find_object(input_str: str) -> str:
    """
    Finds an object by asking the user where it is. If the user doesn't know, automatically starts a physical search.
    Similar to find_person but for objects.
    The input should be a JSON string with 'object_name' key, for example: '{"object_name": "glass"}'.
    """
    try:
        # Parse input
        if input_str.startswith("'") and input_str.endswith("'"):
            input_str = input_str[1:-1]
        
        parsed_input = json.loads(input_str)
        object_name = parsed_input.get("object_name")
        
        if not object_name:
            return "Error: 'object_name' key is required in input JSON for find_object."
        
        print(f"[ROBOT ACTION] Looking for {object_name}...")
        
        # Ask the user where the object is
        user_response = ask_user(f"Where is the {object_name}?")
        
        # If user doesn't know, start automatic search
        if user_response == "__UNKNOWN_LOCATION__":
            print(f"[ROBOT INFO] User doesn't know where {object_name} is. Starting physical search...")
            return search_for_object(json.dumps({"object_name": object_name}))
        
        # Extract room name from user response (handles "it's in the kitchen", "kitchen", "in the bedroom", etc.)
        location_raw = user_response.strip().lower()
        
        # Remove common phrases to extract just the room name
        phrases_to_remove = [
            "it's in the ", "its in the ", "it is in the ",
            "in the ", "at the ", "on the ",
            "it's in ", "its in ", "it is in ",
            "in ", "at ", "on "
        ]
        
        for phrase in phrases_to_remove:
            if location_raw.startswith(phrase):
                location_raw = location_raw[len(phrase):]
                break
        
        # Normalize the room name
        location = normalize_room_name(location_raw.strip())
        print(f"[ROBOT INFO] User said {object_name} is at: {location}")
        
        # Navigate to the location
        navigate_to(json.dumps({"room": location}))
        
        # Try to pick up the object
        pick_result = pick_up_object(json.dumps({"object_name": object_name}))
        
        return pick_result
        
    except json.JSONDecodeError:
        return f"Error: Invalid JSON input for find_object. Ensure it uses double quotes: {input_str}"
    except Exception as e:
        return f"An unexpected error occurred in find_object: {e}"

@tool
def deliver_object(input_str: str) -> str:
    """
    Delivers an object the robot is currently holding to a specified location or person.
    Returns a success or failure message.
    The input should be a JSON string with an 'object_name' key and an optional 'target_location' key,
    for example: '{"object_name": "box", "target_location": "user"}' or '{"object_name": "book"}'.
    """
    try:
        # Tenta remover as aspas simples externas se existirem
        if input_str.startswith("'") and input_str.endswith("'"):
            input_str = input_str[1:-1]
        
        parsed_input = json.loads(input_str)
        object_name = parsed_input.get("object_name")
        target_location = parsed_input.get("target_location", "user")

        if not object_name:
            return "Error: 'object_name' key not found in input JSON for deliver_object."

        print(f"[ROBOT ACTION] Delivering '{object_name}' to '{target_location}'.")
        # Simula a chamada à API de entrega do robô
        return f"Object '{object_name}' delivered to '{target_location}'."
    except json.JSONDecodeError:
        return f"Error: Invalid JSON input for deliver_object. Ensure it uses double quotes: {input_str}"
    except Exception as e:
        return f"An unexpected error occurred in deliver_object: {e}"

@tool
def search_knowledge_base(query: str) -> str:
    """
    Searches the robot's knowledge base (rulebook and documentation) for information.
    Use this tool to get information about:
    - Competition rules and regulations
    - Robot tasks and procedures
    - Scoring systems
    - Navigation guidelines
    - Manipulation instructions
    - General robotic capabilities
    
    Input should be a clear question or search term related to robotics, competition rules, or tasks.
    Example queries: "navigation rules", "object manipulation", "competition scoring", "robot tasks"
    """
    try:
        # Use o RAG pipeline para buscar informações
        context = get_context(query, k=3)
        
        if context and context != "Nenhum contexto relevante encontrado.":
            return f"Based on the knowledge base:\n\n{context}"
        else:
            return "No relevant information found in the knowledge base for this query."
            
    except Exception as e:
        return f"Error searching knowledge base: {e}"

@tool
def search_rules_and_regulations(query: str) -> str:
    """
    Specifically searches for competition rules and regulations.
    Use this tool when users ask about:
    - What is allowed/not allowed in competitions
    - Scoring rules
    - Task specifications
    - Safety regulations
    - Competition procedures
    
    Input should be a question about rules or regulations.
    Example: "manipulation rules", "navigation safety", "scoring system"
    """
    try:
        # Use busca filtrada especificamente para o rulebook
        context = search_with_filter(query, {"tipo": "rulebook"}, k=3)
        
        if context and context != "Nenhum contexto relevante encontrado.":
            return f"According to the competition rules:\n\n{context}"
        else:
            return "No specific rules found for this query."
            
    except Exception as e:
        return f"Error searching rules: {e}"

@tool
def ask_user(input_str: str) -> str:
    """
    Displays a question to the user and waits for an answer.
    If the user says 'I don't know', returns a specific keyword to trigger fallback behavior.
    
    IMPORTANT: If this tool returns "__UNKNOWN_LOCATION__", it means the user does not know
    the location. You MUST then use the search_for_object tool to search all rooms.
    """
    user_response = input(f"\n[Robot]: {input_str}\n[You]: ")
    user_lower = user_response.strip().lower()
    
    # Expanded list of "I don't know" variations
    unknown_responses = {
        "i don't know", "dont know", "don't know", "i dont know",
        "no idea", "not sure", "não sei", "dunno", "idk",
        "i have no idea", "no clue", "not a clue"
    }
    
    # Check if response contains "don't know", "find it", "search", etc.
    if any(phrase in user_lower for phrase in unknown_responses):
        return "__UNKNOWN_LOCATION__"
    
    if any(word in user_lower for word in ["find", "search", "look"]):
        return "__UNKNOWN_LOCATION__"
    
    return user_response

@tool
def update_person_location(input_str: str) -> str:
    """
    Updates or adds a person's location in the known_people list with timestamp.
    Returns a success message.
    The input should be a JSON string with 'person_name' and 'location' keys,
    for example: '{"person_name": "Pedro", "location": "kitchen"}'.
    """
    try:
        # Tenta remover as aspas simples externas se existirem
        if input_str.startswith("'") and input_str.endswith("'"):
            input_str = input_str[1:-1]
        
        parsed_input = json.loads(input_str)
        person_name = parsed_input.get("person_name")
        location = parsed_input.get("location")
        
        if not person_name or not location:
            return "Error: 'person_name' and 'location' keys are required in input JSON for update_person_location."
        
        # Importar datetime para timestamp
        from datetime import datetime
        current_timestamp = datetime.now().isoformat()
        
        # Verifica se a pessoa já existe na lista
        person_found = False
        for person in known_people:
            if person["name"].lower() == person_name.lower():
                # Atualiza localização existente
                person["last_location"] = location
                person["timestamp"] = current_timestamp
                person_found = True
                print(f"[ROBOT INFO] Updated {person_name}'s location to {location}")
                break
        
        # Se não encontrou, adiciona nova pessoa
        if not person_found:
            new_person = {
                "name": person_name,
                "last_location": location,
                "timestamp": current_timestamp
            }
            known_people.append(new_person)
            print(f"[ROBOT INFO] Added {person_name} to known_people at {location}")
        
        return f"Location updated: {person_name} is at {location}."
        
    except json.JSONDecodeError:
        return f"Error: Invalid JSON input for update_person_location. Ensure it uses double quotes: {input_str}"
    except Exception as e:
        return f"An unexpected error occurred in update_person_location: {e}"

@tool
def find_person(input_str: str) -> str:
    """
    Finds a person by checking the known_people list. If the person is known, returns their last known location
    and asks if the user wants the robot to verify. If location is provided by user, uses it directly.
    The input should be a JSON string with 'person_name' key and optional 'message' and 'location' (or 'room') keys,
    for example: '{"person_name": "Pedro"}' or '{"person_name": "Maria", "message": "João is looking for you", "location": "kitchen"}'.
    """
    try:
        # Inicializa o nó ROS2 se necessário
        publisher = init_ros_node()
        
        # Tenta remover as aspas simples externas se existirem
        if input_str.startswith("'") and input_str.endswith("'"):
            input_str = input_str[1:-1]
        
        parsed_input = json.loads(input_str)
        person_name = parsed_input.get("person_name")
        message = parsed_input.get("message", None)
        # Aceita tanto 'location' quanto 'room' para maior flexibilidade
        user_provided_location = parsed_input.get("location") or parsed_input.get("room")
        
        if not person_name:
            return "Error: 'person_name' key is required in input JSON for find_person."
        
        print(f"[ROBOT ACTION] Looking for {person_name}...")
        
        # Se o usuário forneceu a localização, usa ela diretamente
        if user_provided_location:
            print(f"[ROBOT INFO] User provided location: {user_provided_location}")
            # Atualiza ou adiciona a pessoa com a localização fornecida
            update_person_location(json.dumps({"person_name": person_name, "location": user_provided_location}))
            
            # Navega diretamente para a localização
            navigate_to(json.dumps({"room": user_provided_location}))
            publisher.publish_person_search("searching", person_name, known_location=user_provided_location, action="direct_navigation")
            
            # Retorna à Living Room
            print(f"[ROBOT ACTION] Returning to Living Room (home base)...")
            navigate_to(json.dumps({"room": "living room"}))
            
            if message:
                return f"Went to {user_provided_location}, found {person_name} and delivered message: '{message}'. Returned to Living Room."
            else:
                return f"Went to {user_provided_location}, found {person_name}. Location confirmed! Returned to Living Room."
        
        # Verifica se conhece a pessoa
        person_data = None
        for person in known_people:
            if person["name"].lower() == person_name.lower():
                person_data = person
                break
        
        if person_data:
            # Pessoa conhecida - retorna localização e pergunta se quer verificar
            location = person_data["last_location"]
            timestamp = person_data["timestamp"]
            
            # Formatar timestamp para mostrar apenas hora e minuto
            from datetime import datetime
            try:
                dt = datetime.fromisoformat(timestamp)
                formatted_time = dt.strftime("%H:%M")
            except:
                formatted_time = timestamp  # Fallback se houver erro no parsing
            
            response = f"I know {person_name}! Last seen at {location} at {formatted_time}."
            
            if message:
                response += f"\n\nMessage to deliver: '{message}'"
            
            # Publica status de consulta (sem iniciar busca física ainda)
            publisher.publish_person_search("known", person_name, last_location=location, timestamp=timestamp)
            
            # Pergunta se quer que o robô vá verificar
            verify_response = ask_user(f"{response}\n\nWould you like me to go verify? (yes/no)")

            if verify_response.strip().lower() in {"yes", "y", "sim", "s"}:
                # Remove o registro antigo da pessoa
                print(f"[ROBOT INFO] Removing old record of {person_name} from known_people")
                known_people.remove(person_data)
                
                # Reescreve a sentença original com a informação que temos
                original_command = f"Find {person_name}"
                if message:
                    original_command += f", message: {message}"
                
                #print(f"[ROBOT INFO] Rewriting sentence: {original_command}")
                #inserir room na sentença
                rewrite_command = f"{original_command}, in the {location}"
                rewrite_sentence(rewrite_command)
                print(f"[ROBOT INFO] Rewrited sentence: {rewrite_command}")
                
                # Chama find_person novamente (agora a pessoa será desconhecida e iniciará busca física)
                print(f"[ROBOT INFO] Calling find_person again to perform physical search")
                search_input = {"person_name": person_name, "location": location}
                if message:
                    search_input["message"] = message
                
                return find_person(json.dumps(search_input))
            else:
                return f"Understood. {person_name} was last seen at {location}."
        else:
            # Pessoa desconhecida - inicia busca física usando search_for_person
            print(f"[ROBOT INFO] {person_name} is unknown. Starting physical search...")
            publisher.publish_person_search("searching", person_name, action="find")
            
            # Chama search_for_person para fazer a busca física
            search_input = {"person_name": person_name}
            if message:
                search_input["message"] = message
            
            return search_for_person(json.dumps(search_input))
        
    except json.JSONDecodeError:
        return f"Error: Invalid JSON input for find_person. Ensure it uses double quotes: {input_str}"
    except Exception as e:
        return f"An unexpected error occurred in find_person: {e}"

@tool
def search_for_person(input_str: str) -> str:
    """
    Physically searches for a person by navigating through rooms. Uses random probability (75% success, 25% failure).
    Publishes status updates to ROS2 and navigates to each room until person is found or search limit is reached.
    The input should be a JSON string with 'person_name' key, optional 'message' and 'max_rooms' keys,
    for example: '{"person_name": "Pedro", "message": "Maria is looking for you", "max_rooms": 5}'.
    """
    try:
        # Inicializa o nó ROS2 se necessário
        publisher = init_ros_node()
        
        # Tenta remover as aspas simples externas se existirem
        if input_str.startswith("'") and input_str.endswith("'"):
            input_str = input_str[1:-1]
        
        parsed_input = json.loads(input_str)
        person_name = parsed_input.get("person_name")
        message = parsed_input.get("message", None)
        max_rooms = parsed_input.get("max_rooms", len(known_rooms))  # Default: buscar em todas as salas
        
        if not person_name:
            return "Error: 'person_name' key is required in input JSON for search_for_person."
        
        from datetime import datetime
        
        print(f"[ROBOT ACTION] Starting physical search for {person_name}...")
        
        # Publica início da busca
        publisher.publish_person_search("searching", person_name, action="physical_search", max_rooms=max_rooms)
        
        rooms_searched = []
        person_found = False
        found_location = None
        
        # Itera pelas salas
        for i, room in enumerate(known_rooms):
            if i >= max_rooms:
                print(f"[ROBOT INFO] Reached maximum room search limit ({max_rooms})")
                break
            
            # Navega para a sala
            print(f"[ROBOT ACTION] Searching in {room} ({i+1}/{max_rooms})...")
            navigate_to(json.dumps({"room": room}))
            rooms_searched.append(room)
            
            # Publica status atual
            publisher.publish_person_search("searching", person_name, current_room=room, rooms_searched=len(rooms_searched))
            
            # Simula tempo de busca
            time.sleep(0.5)
            
            # SIMULAÇÃO: Verifica no cenário se a pessoa está nesta sala
            if scenario_manager and scenario_manager.check_person_in_room(person_name, room):
                person_found = True
                found_location = room
                print(f"[ROBOT INFO] Found {person_name} in {room}!")
                break
        
        # Resultado da busca
        if person_found:
            # Atualiza localização da pessoa
            update_person_location(json.dumps({"person_name": person_name, "location": found_location}))
            
            # Publica resultado positivo
            publisher.publish_person_search("found", person_name, location=found_location, rooms_searched=len(rooms_searched))
            
            # Informa a pessoa (se houver mensagem)
            if message:
                response = f"Found {person_name} at {found_location}! Delivered message: '{message}'. "
                print(f"[ROBOT ACTION] Delivering message to {person_name}: '{message}'")
            else:
                response = f"Found {person_name} at {found_location}! "
            
            # Retorna à Living Room (local de origem)
            print(f"[ROBOT ACTION] Returning to Living Room (home base)...")
            navigate_to(json.dumps({"room": "living room"}))
            response += "Returning to Living Room."
            
            return response
        else:
            # Não encontrou após busca
            publisher.publish_person_search("not_found", person_name, rooms_searched=len(rooms_searched))
            
            # Pergunta ao usuário se sabe onde a pessoa está
            user_help = ask_user(f"I couldn't find {person_name} after searching {len(rooms_searched)} rooms. Do you know where {person_name} might be?")
            
            # Retorna à Living Room antes de finalizar
            print(f"[ROBOT ACTION] Returning to Living Room (home base)...")
            navigate_to(json.dumps({"room": "living room"}))
            
            if user_help and user_help != "__UNKNOWN_LOCATION__":
                return f"Thank you! I'll remember to look for {person_name} at {user_help} next time. Returned to Living Room."
            else:
                return f"I searched {len(rooms_searched)} rooms but couldn't find {person_name}. They might not be home. Returned to Living Room."
        
    except json.JSONDecodeError:
        return f"Error: Invalid JSON input for search_for_person. Ensure it uses double quotes: {input_str}"
    except Exception as e:
        return f"An unexpected error occurred in search_for_person: {e}"

# função main para testes (pode ser removida ao final)
def main():
    """Função principal para testes do publisher"""
    print("Testing robot_tools with ROS2...")
    
    # Teste da navegação
    test_rooms = [
        '{"room": "kitchen"}',
        '{"room": "living room"}', 
        '{"room": "office"}'
    ]
    
    for room_cmd in test_rooms:
        result = navigate_to(room_cmd)
        print(f"Command: {room_cmd} -> Result: {result}")
        time.sleep(1)
    
    # Cleanup
    global robot_publisher_node
    if robot_publisher_node:
        robot_publisher_node.destroy_node()
    if rclpy.ok():
        rclpy.shutdown()

if __name__ == '__main__':
    main()


# Define a lista robot_tools depois de todas as ferramentas serem definidas.
robot_tools = [
    classify_sentence_semantic, 
    navigate_to, 
    pick_up_object,
    search_for_object,
    find_object,
    deliver_object, 
    ask_user, 
    rewrite_sentence,
    search_knowledge_base,
    search_rules_and_regulations,
    update_person_location,
    find_person,
    search_for_person
]
