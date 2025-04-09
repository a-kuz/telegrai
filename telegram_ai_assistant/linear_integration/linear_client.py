import sys
import os
import json
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import httpx
import re
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import LINEAR_API_KEY, LINEAR_TEAM_MAPPING
from utils.logging_utils import setup_ai_logger

logger = setup_ai_logger()
LINEAR_API_URL = "https://api.linear.app/graphql"

class LinearClient:
    def __init__(self, api_key: str = LINEAR_API_KEY):
        self.api_key = api_key
        if not self.api_key or self.api_key.strip() == "":
            print("ERROR: Linear API key is not set. Please update your .env file with a valid LINEAR_API_KEY.")
            self.is_configured = False
        else:
            self.is_configured = True
            self.headers = {
                "Content-Type": "application/json",
                "Authorization": f"{self.api_key}"
            }
    async def _execute_query(self, query: str, variables: Dict[str, Any] = None) -> Dict[str, Any]:
        if not self.is_configured:
            raise Exception("Linear API client is not properly configured. Missing API key.")
        if variables is None:
            variables = {}
        payload = {
            "query": query,
            "variables": variables
        }
        
        # Log full request details
        logger.info(f"Executing Linear API query:")
        logger.info(f"API URL: {LINEAR_API_URL}")
        logger.info(f"Query: {query}")
        logger.info(f"Variables: {json.dumps(variables, indent=2)}")
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    LINEAR_API_URL,
                    headers=self.headers,
                    json=payload,
                    timeout=30.0  # Add timeout
                )
                
                # Log response status
                logger.info(f"Response status: {response.status_code}")
                
                if response.status_code != 200:
                    # Log full error response
                    logger.error(f"Error response: {response.text}")
                    
                    if response.status_code == 401 or response.status_code == 400:
                        raise Exception(f"Linear API authentication failed. Please check your API key.")
                    else:
                        error_text = response.text
                        try:
                            error_json = response.json()
                            if "errors" in error_json:
                                error_details = json.dumps(error_json["errors"], indent=2)
                                logger.error(f"GraphQL errors: {error_details}")
                                error_text = f"GraphQL errors: {error_details}"
                        except:
                            pass
                        raise Exception(f"Linear API Error: {response.status_code} - {error_text}")
                
                result = response.json()
                # Log successful result (truncated)
                logger.info(f"Received successful response from Linear API")
                
                if "errors" in result:
                    errors = result.get('errors', [])
                    # Log all errors in detail
                    logger.error(f"GraphQL errors in response: {json.dumps(errors, indent=2)}")
                    
                    if errors:
                        # Extract detailed error messages
                        error_messages = []
                        for error in errors:
                            message = error.get('message', 'Unknown error')
                            
                            # Include validation errors if present
                            extensions = error.get('extensions', {})
                            code = extensions.get('code', '')
                            if code == 'VALIDATION_ERROR':
                                validation_errors = extensions.get('validation', {})
                                for field, field_errors in validation_errors.items():
                                    error_messages.append(f"{field}: {', '.join(field_errors)}")
                            
                            error_messages.append(message)
                        
                        error_msg = " | ".join(error_messages)
                        raise Exception(f"GraphQL Error: {error_msg}")
                
                # Log keys in the result data (without full content)
                if "data" in result:
                    logger.info(f"Result data keys: {list(result.get('data', {}).keys())}")
                    
                return result.get("data", {})
        except httpx.RequestError as e:
            logger.error(f"Network error when connecting to Linear API: {str(e)}")
            raise Exception(f"Network error when connecting to Linear API: {str(e)}")
    async def get_teams(self) -> List[Dict[str, Any]]:
        query = """
        query {
          teams {
            nodes {
              id
              name
              key
            }
          }
        }
        """
        result = await self._execute_query(query)
        return result.get("teams", {}).get("nodes", [])
    async def get_team_id_by_name(self, team_name: str) -> Optional[str]:
        teams = await self.get_teams()
        for team in teams:
            if team.get("name", "").lower() == team_name.lower():
                return team.get("id")
        return None
    async def get_team_id_for_chat(self, chat_id: int) -> Optional[str]:
        """Get Linear team ID for a given Telegram chat ID using mapping."""
        team_id = LINEAR_TEAM_MAPPING.get(str(chat_id))
        if not team_id and LINEAR_TEAM_MAPPING.get("default"):
            team_id = LINEAR_TEAM_MAPPING.get("default")
        return team_id
    async def create_issue(self, title: str, description: str, team_id: str,
                          assignee_id: str = None, labels: List[str] = None,
                          due_date: str = None) -> Dict[str, Any]:
        """
        Create a new issue in Linear.
        Args:
            title: Title of the issue
            description: Markdown description
            team_id: Linear team ID
            assignee_id: Linear user ID (optional)
            labels: List of label IDs (optional)
            due_date: Due date in ISO format YYYY-MM-DD (optional)
        Returns:
            Issue data including ID
        """
        variables = {
            "input": {
                "title": title,
                "description": description,
                "teamId": team_id
            }
        }
        if assignee_id:
            variables["input"]["assigneeId"] = assignee_id
        if labels:
            variables["input"]["labelIds"] = labels
        if due_date:
            variables["input"]["dueDate"] = due_date
        query = """
        mutation CreateIssue($input: IssueCreateInput!) {
          issueCreate(input: $input) {
            success
            issue {
              id
              identifier
              title
              description
              url
            }
          }
        }
        """
        result = await self._execute_query(query, variables)
        if result.get("issueCreate", {}).get("success"):
            return result["issueCreate"]["issue"]
        else:
            raise Exception("Failed to create issue")
    async def update_issue(self, issue_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update an existing issue in Linear.
        Args:
            issue_id: Linear issue ID
            data: Dictionary with fields to update (title, description, assigneeId, etc.)
        Returns:
            Updated issue data
        """
        variables = {
            "id": issue_id,
            "input": data
        }
        query = """
        mutation UpdateIssue($id: String!, $input: IssueUpdateInput!) {
          issueUpdate(id: $id, input: $input) {
            success
            issue {
              id
              identifier
              title
              description
              state {
                name
              }
              url
            }
          }
        }
        """
        result = await self._execute_query(query, variables)
        if result.get("issueUpdate", {}).get("success"):
            return result["issueUpdate"]["issue"]
        else:
            raise Exception("Failed to update issue")
    async def get_issue_by_identifier(self, identifier: str) -> Optional[Dict[str, Any]]:
        """
        Get issue details by its identifier (e.g., ENG-123).
        Args:
            identifier: Issue identifier in format TEAM-NUMBER
        Returns:
            Issue data or None if not found
        """
        variables = {
            "identifier": identifier
        }
        query = """
        query GetIssue($identifier: String!) {
          issueSearch(filter: {identifier: {eq: $identifier}}) {
            nodes {
              id
              identifier
              title
              description
              state {
                name
              }
              assignee {
                id
                name
              }
              url
              dueDate
            }
          }
        }
        """
        result = await self._execute_query(query, variables)
        issues = result.get("issueSearch", {}).get("nodes", [])
        if issues:
            return issues[0]
        return None
    async def get_issues_by_state(self, team_id: str, state_name: str) -> List[Dict[str, Any]]:
        """
        Get issues by their state (e.g., 'In Progress', 'Todo').
        Args:
            team_id: Linear team ID
            state_name: State name to filter by
        Returns:
            List of issues in the specified state
        """
        variables = {
            "teamId": team_id,
            "stateName": state_name
        }
        query = """
        query GetIssuesByState($teamId: String!, $stateName: String!) {
          issues(
            filter: {
              team: { id: { eq: $teamId } }
              state: { name: { eq: $stateName } }
            }
          ) {
            nodes {
              id
              identifier
              title
              description
              state {
                name
              }
              assignee {
                id
                name
              }
              url
              dueDate
            }
          }
        }
        """
        result = await self._execute_query(query, variables)
        return result.get("issues", {}).get("nodes", [])
    async def get_due_soon_issues(self, days: int = 7) -> List[Dict[str, Any]]:
        """
        Get issues that are due within the specified number of days.
        Args:
            days: Number of days to consider "due soon"
        Returns:
            List of issues due within the specified time period
        """
        today = datetime.now().date()
        end_date = (today + timedelta(days=days)).isoformat()
        variables = {
            "dueDate": end_date
        }
        query = """
        query GetDueSoonIssues($dueDate: String!) {
          issues(
            filter: {
              dueDate: { lte: $dueDate }
              state: { name: { neq: "Done" } }
            }
          ) {
            nodes {
              id
              identifier
              title
              description
              state {
                name
              }
              assignee {
                id
                name
              }
              url
              dueDate
              team {
                name
                key
              }
            }
          }
        }
        """
        result = await self._execute_query(query, variables)
        return result.get("issues", {}).get("nodes", [])
    async def get_user_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Find a Linear user by name or email.
        Args:
            name: User name or email to search for
        Returns:
            User data or None if not found
        """
        variables = {
            "name": name
        }
        query = """
        query GetUserByName($name: String!) {
          users(filter: {name: {contains: $name}}) {
            nodes {
              id
              name
              email
              displayName
            }
          }
        }
        """
        result = await self._execute_query(query, variables)
        users = result.get("users", {}).get("nodes", [])
        if users:
            return users[0]
        return None

async def main():
    """Simple test function for the Linear client."""
    client = LinearClient()
    try:
        print("1. Testing Linear API connection...")
        teams = await client.get_teams()
        if teams:
            print(f"✅ Successfully connected to Linear API! Found {len(teams)} teams.")
            print("\nTeams:")
            for team in teams:
                print(f"  - {team.get('name')} (ID: {team.get('id')}, Key: {team.get('key')})")
            if len(teams) > 0:
                test_team_id = teams[0]['id']
                print(f"\n2. Creating test issue in team {teams[0]['name']}...")
                try:
                    issue = await client.create_issue(
                        title="Test Issue from Telegram AI Assistant",
                        description="This is a test issue created to verify the Linear integration is working.",
                        team_id=test_team_id
                    )
                    print(f"✅ Successfully created test issue!")
                    print(f"Issue ID: {issue.get('id')}")
                    print(f"Issue Key: {issue.get('identifier')}")
                    print(f"Title: {issue.get('title')}")
                    print(f"URL: {issue.get('url')}")
                except Exception as e:
                    print(f"❌ Error creating test issue: {str(e)}")
        else:
            print("❌ No teams found in your Linear workspace.")
    except Exception as e:
        print(f"❌ Error testing Linear client: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main()) 