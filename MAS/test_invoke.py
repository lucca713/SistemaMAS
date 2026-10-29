from langchain.tools import tool
import json

@tool
def navigate_to(input_str: str) -> str:
    """test"""
    return f"Received: {repr(input_str)}"

print("Test 1:", navigate_to.invoke({"input_str": json.dumps({"room": "porta"})}))
print("Test 2:", navigate_to.invoke(json.dumps({"room": "porta"})))
