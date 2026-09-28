from typing import Any, Optional

from llama_index.core.agent.react.formatter import ReActChatFormatter
from llama_index.core.agent.react.output_parser import ReActOutputParser
from llama_index.core.agent.react.types import (
    ActionReasoningStep,
    ObservationReasoningStep,
)
from llama_index.core.llms import ChatMessage
from llama_index.core.tools import ToolSelection
from llama_index.core.workflow import (
    Context,
    Event,
    StartEvent,
    StopEvent,
    Workflow,
    step,
)

from app.memory import ConversationMemory
from app.traces import AgentTraceLogger


# ============================================================
# Workflow Events
# ============================================================


class PrepEvent(Event):
    """Signals that the workflow should continue reasoning."""


class ToolCallEvent(Event):
    """Represents a tool selected by the agent."""

    tool_call: ToolSelection


class ObservationEvent(Event):
    """Contains the result returned by a tool."""

    observation: str


# ============================================================
# Scheduling Workflow
# ============================================================


class SchedulingWorkflow(Workflow):

    def __init__(
        self,
        memory: ConversationMemory,
        index: Any,
        tracer: AgentTraceLogger,
        evaluator: Optional[Any] = None,
        llm: Optional[Any] = None,
        tools: Optional[list] = None,
        timeout: int = 120,
        verbose: bool = False,
    ):
        super().__init__(
            timeout=timeout,
            verbose=verbose,
        )

        self.memory = memory
        self.index = index
        self.tracer = tracer
        self.evaluator = evaluator
        self.llm = llm
        self.tools = tools or []

        self.formatter = ReActChatFormatter()
        self.output_parser = ReActOutputParser()

    # ============================================================
    # STEP 1 — Prepare
    # ============================================================

    @step
    async def prepare(
        self,
        ctx: Context,
        ev: StartEvent,
    ) -> PrepEvent:

        query = ev.get("query")

        if not query:
            raise ValueError(
                "A query is required."
            )

        # Store user message
        self.memory.add(
            "user",
            query,
        )

        # Trace request
        self.tracer.log(
            "user_request",
            {
                "query": query,
            },
        )

        # System instruction
        messages = [
            ChatMessage(
                role="system",
                content=(
                    "You are an AI healthcare scheduling assistant.\n\n"

                    "Your responsibilities are:\n"
                    "1. Understand healthcare scheduling requests.\n"
                    "2. Search for suitable doctors when necessary.\n"
                    "3. Schedule appointments when the required "
                    "information is available.\n"
                    "4. Never invent doctors or appointment details.\n"
                    "5. Never claim an appointment is confirmed "
                    "unless the scheduling tool confirms it.\n"
                    "6. Ask the user for missing information.\n"
                    "7. Keep responses clear and concise.\n"
                ),
            )
        ]

        # Add conversation history
        for message in self.memory.get():

            role = message.get("role")
            content = message.get("content")

            if role == "user":

                messages.append(
                    ChatMessage(
                        role="user",
                        content=content,
                    )
                )

            elif role == "assistant":

                messages.append(
                    ChatMessage(
                        role="assistant",
                        content=content,
                    )
                )

        # Store messages in workflow context
        await ctx.set(
            "messages",
            messages,
        )

        # Initialize reasoning history
        await ctx.set(
            "reasoning_steps",
            [],
        )

        return PrepEvent()

    # ============================================================
    # STEP 2 — Reason
    # ============================================================

    @step
    async def reasoning(
        self,
        ctx: Context,
        ev: PrepEvent,
    ) -> ToolCallEvent | StopEvent:

        if self.llm is None:

            raise ValueError(
                "LLM has not been provided to "
                "SchedulingWorkflow."
            )

        # Retrieve conversation
        messages = await ctx.get(
            "messages",
            default=[],
        )

        # Retrieve reasoning history
        reasoning_steps = await ctx.get(
            "reasoning_steps",
            default=[],
        )

        # Format ReAct prompt
        formatted_messages = self.formatter.format(
            self.tools,
            messages,
            reasoning_steps,
        )

        # Call LLM
        response = await self.llm.achat(
            formatted_messages
        )

        response_text = response.message.content

        # Trace LLM response
        self.tracer.log(
            "llm_response",
            {
                "response": response_text,
            },
        )

        # Parse response
        reasoning_step = self.output_parser.parse(
            response_text
        )

        # --------------------------------------------------------
        # Final response
        # --------------------------------------------------------

        if not isinstance(
            reasoning_step,
            ActionReasoningStep,
        ):

            final_response = response_text

            self.memory.add(
                "assistant",
                final_response,
            )

            self.tracer.log(
                "final_response",
                {
                    "response": final_response,
                },
            )

            return StopEvent(
                result={
                    "response": final_response,
                    "traces": self.tracer.get_traces(),
                }
            )

        # --------------------------------------------------------
        # Tool call
        # --------------------------------------------------------

        reasoning_steps.append(
            reasoning_step
        )

        await ctx.set(
            "reasoning_steps",
            reasoning_steps,
        )

        tool_call = ToolSelection(
            tool_id=reasoning_step.action,
            tool_name=reasoning_step.action,
            tool_kwargs=reasoning_step.action_input,
        )

        self.tracer.log(
            "tool_call",
            {
                "tool": reasoning_step.action,
                "arguments": reasoning_step.action_input,
            },
        )

        return ToolCallEvent(
            tool_call=tool_call
        )

    # ============================================================
    # STEP 3 — Execute Tool
    # ============================================================

    @step
    async def execute_tool(
        self,
        ctx: Context,
        ev: ToolCallEvent,
    ) -> ObservationEvent:

        tool_call = ev.tool_call

        selected_tool = None

        # Find tool
        for tool in self.tools:

            try:
                tool_name = tool.metadata.name
            except Exception:
                continue

            if tool_name == tool_call.tool_name:
                selected_tool = tool
                break

        # Tool not found
        if selected_tool is None:

            error_message = (
                f"Tool '{tool_call.tool_name}' "
                f"was not found."
            )

            self.tracer.log(
                "tool_error",
                {
                    "tool": tool_call.tool_name,
                    "error": error_message,
                },
            )

            return ObservationEvent(
                observation=error_message
            )

        # Execute tool
        try:

            result = await selected_tool.acall(
                **tool_call.tool_kwargs
            )

            observation = str(result)

            self.tracer.log(
                "tool_result",
                {
                    "tool": tool_call.tool_name,
                    "result": observation,
                },
            )

            return ObservationEvent(
                observation=observation
            )

        except Exception as exc:

            error_message = (
                f"Tool execution failed: {str(exc)}"
            )

            self.tracer.log(
                "tool_error",
                {
                    "tool": tool_call.tool_name,
                    "error": str(exc),
                },
            )

            return ObservationEvent(
                observation=error_message
            )

    # ============================================================
    # STEP 4 — Observe
    # ============================================================

    @step
    async def observe(
        self,
        ctx: Context,
        ev: ObservationEvent,
    ) -> PrepEvent:

        reasoning_steps = await ctx.get(
            "reasoning_steps",
            default=[],
        )

        # Add observation to reasoning history
        reasoning_steps.append(
            ObservationReasoningStep(
                observation=ev.observation
            )
        )

        await ctx.set(
            "reasoning_steps",
            reasoning_steps,
        )

        # Continue the reasoning loop
        return PrepEvent()