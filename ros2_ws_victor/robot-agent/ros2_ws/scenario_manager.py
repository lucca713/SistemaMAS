"""
Scenario Manager - Simulates the real world state for testing
This module reads scenario JSON files and provides sensor-like feedback to the robot agent.
The agent NEVER directly accesses this - it only receives information through tool responses.
"""

import json
import os
from typing import Optional, List, Dict, Any


class ScenarioManager:
    """
    Manages the current scenario state and provides simulated sensor feedback.
    This represents the "ground truth" of the world that the agent must discover.
    """
    
    def __init__(self, scenario_path: Optional[str] = None):
        """
        Initialize the scenario manager.
        
        Args:
            scenario_path: Path to the scenario JSON file. 
                          If None, uses default baseline_house_1.json
        """
        if scenario_path is None:
            # Default to baseline scenario
            base_dir = os.path.dirname(os.path.abspath(__file__))
            scenario_path = os.path.join(base_dir, '..', 'Scenarios', 'baseline_house_1.json')
        
        self.scenario_path = scenario_path
        self.scenario = self._load_scenario()
        
    def _load_scenario(self) -> Dict[str, Any]:
        """Load scenario from JSON file."""
        try:
            with open(self.scenario_path, 'r') as f:
                scenario = json.load(f)
            print(f"[ScenarioManager] Loaded scenario: {scenario.get('scenario_name', 'unknown')}")
            return scenario
        except FileNotFoundError:
            print(f"[ScenarioManager] Warning: Scenario file not found at {self.scenario_path}")
            return {"scenario_name": "empty", "people": [], "objects": []}
        except json.JSONDecodeError as e:
            print(f"[ScenarioManager] Error parsing scenario JSON: {e}")
            return {"scenario_name": "empty", "people": [], "objects": []}
    
    def reload_scenario(self):
        """Reload the scenario from file (useful for testing different scenarios)."""
        self.scenario = self._load_scenario()
    
    def get_scenario_name(self) -> str:
        """Get the name of the current scenario."""
        return self.scenario.get('scenario_name', 'unknown')
    
    # ==================== PEOPLE-RELATED METHODS ====================
    
    def check_person_in_room(self, person_name: str, room: str) -> bool:
        """
        Simulate sensor: Is this person in this room?
        
        Args:
            person_name: Name of the person to check
            room: Room to check in
            
        Returns:
            True if person is in the room, False otherwise
        """
        person_name_lower = person_name.lower().strip()
        room_lower = room.lower().strip()
        
        for person in self.scenario.get('people', []):
            if person['name'].lower() == person_name_lower:
                return person['location'].lower() == room_lower
        
        return False
    
    def get_person_location(self, person_name: str) -> Optional[str]:
        """
        Get the actual location of a person (for validation/testing purposes).
        WARNING: The agent should NOT have direct access to this!
        
        Args:
            person_name: Name of the person
            
        Returns:
            Room name where the person is located, or None if not found
        """
        person_name_lower = person_name.lower().strip()
        
        for person in self.scenario.get('people', []):
            if person['name'].lower() == person_name_lower:
                return person['location']
        
        return None
    
    def get_people_in_room(self, room: str) -> List[str]:
        """
        Get list of people in a specific room.
        
        Args:
            room: Room to check
            
        Returns:
            List of person names in that room
        """
        room_lower = room.lower().strip()
        people = []
        
        for person in self.scenario.get('people', []):
            if person['location'].lower() == room_lower:
                people.append(person['name'])
        
        return people
    
    def get_all_people(self) -> List[Dict[str, str]]:
        """
        Get all people in the scenario.
        
        Returns:
            List of dicts with 'name' and 'location' keys
        """
        return self.scenario.get('people', [])
    
    # ==================== OBJECT-RELATED METHODS ====================
    
    def get_objects_in_room(self, room: str) -> List[Dict[str, Any]]:
        """
        Simulate sensor: What objects are visible in this room?
        
        Args:
            room: Room to check
            
        Returns:
            List of objects in the room (each object is a dict with type, location, weight_kg)
        """
        room_lower = room.lower().strip()
        objects = []
        
        for obj in self.scenario.get('objects', []):
            if obj['location'].lower() == room_lower:
                objects.append(obj)
        
        return objects
    
    def check_object_in_room(self, object_type: str, room: str) -> bool:
        """
        Check if a specific type of object exists in a room.
        
        Args:
            object_type: Type of object (e.g., "cup", "book")
            room: Room to check
            
        Returns:
            True if at least one object of this type is in the room
        """
        object_type_lower = object_type.lower().strip()
        room_lower = room.lower().strip()
        
        for obj in self.scenario.get('objects', []):
            if (obj['type'].lower() == object_type_lower and 
                obj['location'].lower() == room_lower):
                return True
        
        return False
    
    def get_object_weight(self, object_type: str, room: str) -> Optional[float]:
        """
        Get the weight of an object in a specific room.
        
        Args:
            object_type: Type of object
            room: Room where the object is located
            
        Returns:
            Weight in kg, or None if object not found
        """
        object_type_lower = object_type.lower().strip()
        room_lower = room.lower().strip()
        
        for obj in self.scenario.get('objects', []):
            if (obj['type'].lower() == object_type_lower and 
                obj['location'].lower() == room_lower):
                return obj.get('weight_kg')
        
        return None
    
    def can_lift_object(self, object_type: str, room: str, max_weight: float = 3.0) -> bool:
        """
        Check if the robot can lift an object based on weight constraints.
        
        Args:
            object_type: Type of object
            room: Room where the object is located
            max_weight: Maximum weight the robot can lift (default 3.0 kg)
            
        Returns:
            True if object can be lifted, False otherwise
        """
        weight = self.get_object_weight(object_type, room)
        if weight is None:
            return False
        return weight <= max_weight
    
    # ==================== UTILITY METHODS ====================
    
    def get_all_rooms(self) -> List[str]:
        """
        Get list of all rooms mentioned in the scenario.
        
        Returns:
            List of unique room names
        """
        rooms = set()
        for person in self.scenario.get('people', []):
            rooms.add(person['location'])
        for obj in self.scenario.get('objects', []):
            rooms.add(obj['location'])
        return sorted(list(rooms))
    
    def get_scenario_summary(self) -> str:
        """
        Get a human-readable summary of the scenario.
        Useful for debugging and testing.
        
        Returns:
            Formatted string with scenario information
        """
        people_count = len(self.scenario.get('people', []))
        objects_count = len(self.scenario.get('objects', []))
        rooms = self.get_all_rooms()
        
        summary = f"Scenario: {self.get_scenario_name()}\n"
        summary += f"Rooms: {len(rooms)} ({', '.join(rooms)})\n"
        summary += f"People: {people_count}\n"
        summary += f"Objects: {objects_count}\n"
        
        return summary


# Global instance for easy access (initialized when first imported)
_global_scenario_manager: Optional[ScenarioManager] = None


def get_scenario_manager(scenario_path: Optional[str] = None) -> ScenarioManager:
    """
    Get or create the global scenario manager instance.
    
    Args:
        scenario_path: Path to scenario file (only used on first call)
        
    Returns:
        ScenarioManager instance
    """
    global _global_scenario_manager
    
    if _global_scenario_manager is None:
        _global_scenario_manager = ScenarioManager(scenario_path)
    
    return _global_scenario_manager


def set_scenario(scenario_path: str):
    """
    Change the active scenario.
    
    Args:
        scenario_path: Path to new scenario JSON file
    """
    global _global_scenario_manager
    _global_scenario_manager = ScenarioManager(scenario_path)


# Example usage and testing
if __name__ == "__main__":
    print("=== Scenario Manager Test ===\n")
    
    # Create scenario manager
    manager = ScenarioManager()
    
    # Print summary
    print(manager.get_scenario_summary())
    print()
    
    # Test person location
    print("=== Testing Person Location ===")
    test_people = ["Ana", "Bruno", "Carla", "Diego", "Unknown"]
    for person in test_people:
        location = manager.get_person_location(person)
        print(f"{person}: {location if location else 'Not found'}")
    print()
    
    # Test person in room
    print("=== Testing Person in Room ===")
    print(f"Is Ana in kitchen? {manager.check_person_in_room('Ana', 'kitchen')}")
    print(f"Is Bruno in bedroom? {manager.check_person_in_room('Bruno', 'bedroom')}")
    print(f"Is Carla in bedroom? {manager.check_person_in_room('Carla', 'bedroom')}")
    print()
    
    # Test objects in room
    print("=== Testing Objects in Kitchen ===")
    kitchen_objects = manager.get_objects_in_room('kitchen')
    print(f"Found {len(kitchen_objects)} objects in kitchen:")
    for obj in kitchen_objects[:5]:  # Show first 5
        print(f"  - {obj['type']} ({obj['weight_kg']} kg)")
    print()
    
    # Test object weight and lifting
    print("=== Testing Object Weight and Lifting ===")
    test_objects = [
        ("cup", "kitchen"),
        ("refrigerator", "kitchen"),
        ("bed", "bedroom")
    ]
    for obj_type, room in test_objects:
        weight = manager.get_object_weight(obj_type, room)
        can_lift = manager.can_lift_object(obj_type, room)
        print(f"{obj_type} in {room}: {weight} kg - Can lift: {can_lift}")
