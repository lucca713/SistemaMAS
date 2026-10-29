#!/usr/bin/env python3
"""
Test script to verify scenario manager object detection
"""

from scenario_manager import get_scenario_manager

def test_object_locations():
    """Test object locations in the scenario"""
    
    print("=" * 60)
    print("TEST: Object Locations in Scenario")
    print("=" * 60)
    
    # Initialize scenario
    sm = get_scenario_manager()
    print(f"\nScenario loaded: {sm.get_scenario_name()}\n")
    
    # Test cases
    test_cases = [
        ("pen", "living room", False, "Pen should NOT be in living room"),
        ("pen", "bedroom", True, "Pen should be in bedroom"),
        ("cup", "kitchen", True, "Cup should be in kitchen"),
        ("refrigerator", "kitchen", True, "Refrigerator should be in kitchen"),
        ("book", "living room", True, "Book should be in living room"),
        ("remote control", "living room", True, "Remote control should be in living room"),
    ]
    
    print("Running tests...")
    passed = 0
    failed = 0
    
    for obj_type, room, expected, description in test_cases:
        result = sm.check_object_in_room(obj_type, room)
        status = "✓ PASS" if result == expected else "✗ FAIL"
        
        if result == expected:
            passed += 1
        else:
            failed += 1
        
        print(f"{status}: {description}")
        print(f"   Expected: {expected}, Got: {result}")
        
        # Show weight if object exists
        if result:
            weight = sm.get_object_weight(obj_type, room)
            can_lift = sm.can_lift_object(obj_type, room, max_weight=5.0)
            print(f"   Weight: {weight} kg, Can lift: {can_lift}")
        print()
    
    print("=" * 60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 60)

if __name__ == "__main__":
    test_object_locations()
