# Scenario Files

This directory contains scenario JSON files that define the "ground truth" state of the simulated environment.

## Purpose

The scenario files are used to simulate a real-world house environment for testing and validating the robot agent's capabilities. The robot agent **does not have direct access** to these files - they are only used by the `scenario_manager.py` module to provide simulated sensor feedback.

## Structure

Each scenario JSON file contains:

```json
{
  "scenario_name": "string - name of the scenario",
  "people": [
    {
      "name": "string - person's name (Brazilian Portuguese names)",
      "location": "string - room where the person is located"
    }
  ],
  "objects": [
    {
      "type": "string - object type (e.g., 'cup', 'book')",
      "location": "string - room where the object is located",
      "weight_kg": "number - weight in kilograms"
    }
  ]
}
```

## Available Rooms

All scenarios use the following standard rooms:
- bedroom
- dining room
- living room
- kitchen
- laundry room
- hall
- garage
- bathroom

## How It Works

1. **Robot Agent Knowledge**: The robot knows the house structure (rooms) from `house_structure.yaml` in the `ros2_ws` directory, but NOT the current state (where people/objects are).

2. **Simulation**: When the robot performs actions like `search_for_person` or `navigate_to`, the `scenario_manager.py` reads this JSON file and simulates sensor feedback (e.g., "Yes, Ana is in the kitchen" when the robot navigates there).

3. **Discovery**: The robot must physically navigate to rooms and "discover" people and objects, just like in the real world. It cannot cheat by reading this file directly.

## Creating New Scenarios

To create a new scenario:

1. Copy `baseline_house_1.json`
2. Rename it (e.g., `custom_scenario_1.json`)
3. Modify the people and objects as needed
4. Use 3-5 people (Brazilian Portuguese names)
5. Place objects realistically (e.g., cups in kitchen, books in living room/bedroom)
6. Set realistic weights for objects

## Current Scenarios

- **baseline_house_1.json**: Default scenario with 4 people (Ana, Bruno, Carla, Diego) and 65+ objects distributed across all rooms.
