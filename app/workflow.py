from typing import Any, Dict, List, Optional

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
from app.tools import (
    schedule_appointment_tool,
    search_doctors_tool,
)


# -------------------------------------------------------------------
# Workflow Events
# -------------------------------------------------------------------

class InputEvent(Event):
    """Contains the user's input query."""
    query: str


class PrepEvent(Event):
    """Prepared input for the reasoning loop."""
    input: List[ChatMessage]


class ToolCallEvent(Event):
    """Represents a tool call requested by the agent."""
    tool_call: ToolSelection


class ObservationEvent(Event):
    """Contains the result returned by a tool."""
    observation: str


# -------------------------------------------------------------------
# Scheduling Workflow
# -------------------------------------------------------------------

class SchedulingWorkflow(Workflow):

    def __init__(
        self,
        memory: ConversationMemory,
        index: Any,
        tracer: AgentTraceLogger,
        evaluator: Optional[Any] = None,
        llm: Optional[Any] = None,
        timeout: int = 120,
        verbose: bool = False,
    ):
        super().__init__(timeout=timeout, verbose=verbose)

        self.memory = memory
        self.index = index
        self.tracer = tracer
        self.evaluator = evaluator
        self.llm = llm

        # -----------------------------------------------------------
        # Tools
        # -----------------------------------------------------------

        self.tools = [
            search_doctors_tool,
            schedule_appointment_tool,
        ]

        # -----------------------------------------------------------
        # ReAct components
        # -----------------------------------------------------------

        self.formatter = ReActChatFormatter()
        self.output_parser = ReActOutputParser()

    # ----------------------------------------------------------------
    # STEP 1: Prepare the user request
    # ----------------------------------------------------------------

    @step
    async def prepare(self, ctx: Context, ev: StartEvent) -> PrepEvent:

        query = ev.get("query")

        if not query:
            raise ValueError("Query is required.")

        # Store user message in memory
        self.memory.add("user", query)

        # Trace
        self.tracer.log(
            "user_request",
            {
                "query": query
            }
        )

        # Build conversation messages
        messages = []

        # System instruction
        messages.append(
            ChatMessage(
                role="system",
                content=(
                    "You are a healthcare scheduling assistant.\n\n"
                    "Your responsibilities are:\n"
                    "1. Understand the patient's request.\n"
                    "2. Search for suitable doctors when necessary.\n"
                    "3. Schedule an appointment when the user provides "
                    "the required information.\n"
                    "4. Never claim an appointment is confirmed unless "
                    "the scheduling tool confirms it.\n"
                    "5. Ask for missing information when necessary.\n"
                    "6. Provide concise and clear responses.\n"
                ),
            )
        )

        # Previous conversation
        for message in self.memory.get():

            role = message["role"]

            if role == "user":
                messages.append(
                    ChatMessage(
                        role="user",
                        content=message["content"],
                    )
                )

            elif role == "assistant":
                messages.append(
                    ChatMessage(
                        role="assistant",
                        content=message["content"],
                    )
                )

        return PrepEvent(input=messages)

    # ----------------------------------------------------------------
    # STEP 2: Agent reasoning
    # ----------------------------------------------------------------

    @step
    async def reasoning(
        self,
        ctx: Context,
        ev: PrepEvent,
    ) -> ToolCallEvent | StopEvent:

        if self.llm is None:
            raise ValueError(
                "LLM has not been provided to SchedulingWorkflow."
            )

        # Retrieve previous reasoning steps
        reasoning_steps = await ctx.get(
            "reasoning_steps",
            default=[],
        )

        # Format messages for ReAct
        chat_history = ev.input

        response = await self.llm.achat(
            self.formatter.format(
                self.tools,
                chat_history,
                reasoning_steps,
            )
        )

        # Parse LLM response
        reasoning_step = self.output_parser.parse(response.message.content)

        # ------------------------------------------------------------
        # Final answer
        # ------------------------------------------------------------

        if not isinstance(
            reasoning_step,
            ActionReasoningStep,
        ):

            final_response = response.message.content

            self.memory.add(
                "assistant",
                final_response,
            )

            self.tracer.log(
                "final_response",
                {
                    "response": final_response
                }
            )

            return StopEvent(
                result={
                    "response": final_response,
                    "traces": self.tracer.get_traces(),
                }
            )

        # ------------------------------------------------------------
        # Tool call
        # ------------------------------------------------------------

        reasoning_steps.append(reasoning_step)

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
            }
        )

        return ToolCallEvent(
            tool_call=tool_call
        )

    # ----------------------------------------------------------------
    # STEP 3: Execute tool
    # ----------------------------------------------------------------

    @step
    async def execute_tool(
        self,
        ctx: Context,
        ev: ToolCallEvent,
    ) -> ObservationEvent:

        tool_call = ev.tool_call

        selected_tool = None

        for tool in self.tools:

            if tool.metadata.name == tool_call.tool_name:
                selected_tool = tool
                break

        if selected_tool is None:

            error_message = (
                f"Tool '{tool_call.tool_name}' was not found."
            )

            self.tracer.log(
                "tool_error",
                {
                    "tool": tool_call.tool_name,
                    "error": error_message,
                }
            )

            return ObservationEvent(
                observation=error_message
            )

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
                }
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
                }
            )

            return ObservationEvent(
                observation=error_message
            )

    # ----------------------------------------------------------------
    # STEP 4: Add observation and continue reasoning
    # ----------------------------------------------------------------

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

        reasoning_steps.append(
            ObservationReasoningStep(
                observation=ev.observation
            )
        )

        await ctx.set(
            "reasoning_steps",
            reasoning_steps,
        )

        # Get original messages
        messages = await ctx.get(
            "messages",
            default=None,
        )

        if messages is None:

            # Reconstruct from memory
            messages = []

            for message in self.memory.get():

                if message["role"] == "user":

                    messages.append(
                        ChatMessage(
                            role="user",
                            content=message["content"],
                        )
                    )

                elif message["role"] == "assistant":

                    messages.append(
                        ChatMessage(
                            role="assistant",
                            content=message["content"],
                        )
                    )

            await ctx.set(
                "messages",
                messages,
            )

        return PrepEvent(
            input=messages
        )

    # ----------------------------------------------------------------
    # Override prepare to preserve context
    # ----------------------------------------------------------------

    @step
    async def initialize_context(
        self,
        ctx: Context,
        ev: PrepEvent,
    ) -> PrepEvent:

        await ctx.set(
            "messages",
            ev.input,
        )

        await ctx.set(
            "reasoning_steps",
            [],
        )

        return ev