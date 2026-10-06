from collections import defaultdict
from time import time


class AgentEvaluator:
    def __init__(self):
        self.metrics = defaultdict(int)
        self.latencies = []

    def log_intent(self, predicted: str, expected: str):
        if predicted == expected:
            self.metrics["correct_intent"] += 1
        self.metrics["total_intent"] += 1

    def log_tool(self, predicted: str, expected: str):
        if predicted == expected:
            self.metrics["correct_tool"] += 1
        self.metrics["total_tool"] += 1

    def log_task(self, success: bool):
        if success:
            self.metrics["successful_tasks"] += 1
        self.metrics["total_tasks"] += 1

    def log_invalid_action(self):
        self.metrics["invalid_actions"] += 1

    def log_latency(self, duration: float):
        self.latencies.append(duration)

    def report(self):
        return {
            "intent_accuracy": self._safe_div("correct_intent", "total_intent"),
            "tool_accuracy": self._safe_div("correct_tool", "total_tool"),
            "task_completion_rate": self._safe_div("successful_tasks", "total_tasks"),
            "invalid_action_rate": self._safe_div("invalid_actions", "total_tasks"),
            "avg_latency_sec": sum(self.latencies) / len(self.latencies) if self.latencies else 0.0,
        }

    def _safe_div(self, a, b):
        return round(self.metrics[a] / self.metrics[b], 3) if self.metrics[b] else 0.0
