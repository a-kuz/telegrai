import sys
import os
import asyncio
import json
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from linear_integration.linear_client import LinearClient
async def main():
    """Get all teams from Linear and display their IDs and names."""
    print("Fetching teams from Linear...")
    client = LinearClient()
    try:
        teams = await client.get_teams()
        if not teams:
            print("No teams found. Make sure your LINEAR_API_KEY is correct.")
            return
        print("\nTeams in your Linear workspace:")
        print("-" * 40)
        print(f"{'Team Name':<20} {'Team Key':<10} {'Team ID'}")
        print("-" * 40)
        for team in teams:
            print(f"{team.get('name', 'Unknown'):<20} {team.get('key', 'N/A'):<10} {team.get('id', 'Unknown')}")
        print("\nExample LINEAR_TEAM_MAPPING configuration:")
        example_mapping = {"default": teams[0]["id"]}
        if len(teams) > 1:
            example_mapping["example_chat_id"] = teams[1]["id"]
        print(f'LINEAR_TEAM_MAPPING={json.dumps(example_mapping)}')
        print("\nReplace 'example_chat_id' with your actual Telegram chat IDs.")
    except Exception as e:
        print(f"Error fetching teams: {str(e)}")
if __name__ == "__main__":
    asyncio.run(main()) 