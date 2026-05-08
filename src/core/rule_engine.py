import logging
import json
from typing import Dict, Any, List, Callable, Union

logger = logging.getLogger(__name__)

class RuleAction:
    """Defines an action to be taken when a rule matches."""
    def __init__(self, action_type: str, payload: Dict[str, Any]):
        self.action_type = action_type
        self.payload = payload

    def execute(self, data: Dict[str, Any]) -> None:
        """Executes the defined action with the given data context."""
        logger.info(f"Executing action '{self.action_type}' with payload: {self.payload} for data: {data}")
        # In a real system, this would dispatch to a message queue, another service, etc.
        if self.action_type == "log_alert":
            logger.warning(f"RULE ALERT: {self.payload.get('message', 'No message')} - Data: {json.dumps(data)}")
        elif self.action_type == "enrich_data":
            # Example: add a tag or new field
            tag = self.payload.get('tag', 'rule_matched')
            data['tags'] = data.get('tags', [])
            if tag not in data['tags']:
                data['tags'].append(tag)
            logger.debug(f"Data enriched with tag: {tag}")
        else:
            logger.warning(f"Unknown action type: {self.action_type}")

class RuleCondition:
    """Represents a single condition within a rule."""
    def __init__(self, field: str, operator: str, value: Any):
        self.field = field
        self.operator = operator
        self.value = value

    def evaluate(self, data: Dict[str, Any]) -> bool:
        """Evaluates the condition against the provided data."""
        data_value = self._get_nested_value(data, self.field)

        if data_value is None:
            return False

        try:
            if self.operator == "eq":
                return data_value == self.value
            elif self.operator == "ne":
                return data_value != self.value
            elif self.operator == "gt":
                return data_value > self.value
            elif self.operator == "lt":
                return data_value < self.value
            elif self.operator == "ge":
                return data_value >= self.value
            elif self.operator == "le":
                return data_value <= self.value
            elif self.operator == "contains":
                return self.value in str(data_value)
            elif self.operator == "in":
                return data_value in self.value if isinstance(self.value, (list, tuple, set)) else False
            elif self.operator == "not_in":
                return data_value not in self.value if isinstance(self.value, (list, tuple, set)) else False
            elif self.operator == "has_field":
                return data_value is not None
            else:
                logger.warning(f"Unknown operator: {self.operator}")
                return False
        except TypeError as e:
            logger.error(f"Type error during rule evaluation for field '{self.field}': {e}")
            return False

    def _get_nested_value(self, data: Dict[str, Any], field_path: str) -> Any:
        """Retrieves a value from a nested dictionary using a dot-separated path."""
        parts = field_path.split('.')
        current_value = data
        for part in parts:
            if isinstance(current_value, dict):
                current_value = current_value.get(part)
            else:
                return None # Path segment does not lead to a dict
            if current_value is None:
                break
        return current_value

class Rule:
    """Represents a single rule with multiple conditions and associated actions."""
    def __init__(self, rule_id: str, description: str, conditions: List[RuleCondition], actions: List[RuleAction], logical_operator: str = "AND"):
        self.rule_id = rule_id
        self.description = description
        self.conditions = conditions
        self.actions = actions
        self.logical_operator = logical_operator.upper() # 'AND' or 'OR'

        if self.logical_operator not in ("AND", "OR"):
            raise ValueError("Logical operator must be 'AND' or 'OR'.")

    def matches(self, data: Dict[str, Any]) -> bool:
        """Checks if the rule's conditions are met by the provided data."""
        if not self.conditions:
            return True # No conditions means it always matches (or is a no-op rule)

        results = [condition.evaluate(data) for condition in self.conditions]

        if self.logical_operator == "AND":
            return all(results)
        elif self.logical_operator == "OR":
            return any(results)
        return False

    def execute_actions(self, data: Dict[str, Any]) -> None:
        """Executes all associated actions for the rule."""
        for action in self.actions:
            action.execute(data)

class RuleEngine:
    """Manages and evaluates a collection of rules against incoming data streams."""
    def __init__(self):
        self._rules: Dict[str, Rule] = {}

    def add_rule(self, rule: Rule) -> None:
        """Adds a rule to the engine."""
        if rule.rule_id in self._rules:
            logger.warning(f"Rule with ID '{rule.rule_id}' already exists. Overwriting.")
        self._rules[rule.rule_id] = rule
        logger.info(f"Rule '{rule.rule_id}' added.")

    def remove_rule(self, rule_id: str) -> None:
        """Removes a rule from the engine by its ID."""
        if rule_id in self._rules:
            del self._rules[rule_id]
            logger.info(f"Rule '{rule_id}' removed.")
        else:
            logger.warning(f"Attempted to remove non-existent rule: '{rule_id}'.")

    def process_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Evaluates all registered rules against the incoming data and executes actions."""
        processed_data = data.copy() # Operate on a copy to allow in-place modification by actions
        matched_rule_ids = []

        for rule_id, rule in self._rules.items():
            if rule.matches(processed_data):
                logger.debug(f"Rule '{rule_id}' matched for data: {json.dumps(processed_data)}")
                rule.execute_actions(processed_data)
                matched_rule_ids.append(rule_id)
        
        if matched_rule_ids:
            processed_data['rule_matches'] = matched_rule_ids
            logger.info(f"Data processed by rules. Matched rules: {matched_rule_ids}")
        
        return processed_data

    @classmethod
    def from_config(cls, config_path: str) -> 'RuleEngine':
        """Constructs a RuleEngine instance from a JSON configuration file."""
        engine = cls()
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)

            for rule_config in config.get('rules', []):
                rule_id = rule_config['id']
                description = rule_config.get('description', 'No description')
                logical_operator = rule_config.get('logical_operator', 'AND')
                
                conditions = []
                for cond_config in rule_config.get('conditions', []):
                    conditions.append(RuleCondition(
                        field=cond_config['field'],
                        operator=cond_config['operator'],
                        value=cond_config['value']
                    ))

                actions = []
                for action_config in rule_config.get('actions', []):
                    actions.append(RuleAction(
                        action_type=action_config['type'],
                        payload=action_config.get('payload', {})
                    ))
                
                engine.add_rule(Rule(rule_id, description, conditions, actions, logical_operator))
            logger.info(f"RuleEngine initialized with {len(engine._rules)} rules from {config_path}.")
        except FileNotFoundError:
            logger.error(f"Rule configuration file not found: {config_path}")
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding JSON from {config_path}: {e}")
        except KeyError as e:
            logger.error(f"Missing required key in rule configuration: {e}")
        except Exception as e:
            logger.error(f"Unexpected error loading rules: {e}")
        return engine

# Example Usage and Configuration Structure (for documentation purposes)
# This would typically be in a separate test or documentation file.
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

    # Example rule configuration JSON structure
    example_config = {
        "rules": [
            {
                "id": "high_severity_keyword_alert",
                "description": "Alert for critical keywords in OSINT reports",
                "logical_operator": "OR",
                "conditions": [
                    {"field": "report.content", "operator": "contains", "value": "exploit"},
                    {"field": "report.content", "operator": "contains", "value": "vulnerability"},
                    {"field": "source.reputation", "operator": "eq", "value": "low"}
                ],
                "actions": [
                    {"type": "log_alert", "payload": {"message": "High severity OSINT finding!"}},
                    {"type": "enrich_data", "payload": {"tag": "critical_threat"}}
                ]
            },
            {
                "id": "specific_actor_watch",
                "description": "Monitor mentions of a specific threat actor",
                "logical_operator": "AND",
                "conditions": [
                    {"field": "report.actor_id", "operator": "eq", "value": "APT-28"},
                    {"field": "report.timestamp", "operator": "gt", "value": "2023-01-01T00:00:00Z"}
                ],
                "actions": [
                    {"type": "log_alert", "payload": {"message": "APT-28 mentioned recently."}},
                    {"type": "enrich_data", "payload": {"tag": "actor_watch"}}
                ]
            }
        ]
    }

    # Save example config to a temporary file
    config_file_path = "rules_config.json"
    with open(config_file_path, 'w') as f:
        json.dump(example_config, f, indent=4)

    # Initialize engine from config
    engine = RuleEngine.from_config(config_file_path)

    # Test data
    data_stream_1 = {
        "id": "osint_report_1",
        "timestamp": "2023-03-15T10:00:00Z",
        "source": {"name": "DarkWebForum", "reputation": "low"},
        "report": {
            "title": "New Zero-Day Exploit Found",
            "content": "Details of a critical Windows exploit being discussed.",
            "actor_id": "UNKNOWN"
        }
    }

    data_stream_2 = {
        "id": "osint_report_2",
        "timestamp": "2023-03-15T11:00:00Z",
        "source": {"name": "ThreatIntelFeed", "reputation": "high"},
        "report": {
            "title": "Activity attributed to APT-28",
            "content": "Recent phishing campaigns by APT-28 targeting energy sector.",
            "actor_id": "APT-28"
        }
    }

    data_stream_3 = {
        "id": "osint_report_3",
        "timestamp": "2022-12-01T09:00:00Z",
        "source": {"name": "NewsSite", "reputation": "medium"},
        "report": {
            "title": "Old APT-28 activity",
            "content": "Historical data on APT-28 operations.",
            "actor_id": "APT-28"
        }
    }

    print("\n--- Processing Data Stream 1 ---")
    processed_data_1 = engine.process_data(data_stream_1)
    print(f"Final Data 1: {json.dumps(processed_data_1, indent=2)}")

    print("\n--- Processing Data Stream 2 ---")
    processed_data_2 = engine.process_data(data_stream_2)
    print(f"Final Data 2: {json.dumps(processed_data_2, indent=2)}")

    print("\n--- Processing Data Stream 3 ---")
    processed_data_3 = engine.process_data(data_stream_3)
    print(f"Final Data 3: {json.dumps(processed_data_3, indent=2)}")

    # Clean up temporary config file
    import os
    os.remove(config_file_path)
