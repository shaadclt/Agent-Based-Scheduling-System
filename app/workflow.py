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
    """Prepared conversation input for the agent."""


class ToolCallEvent(Event):
    """Represents a tool call selected by the agent."""

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

        # --------------------------------------------------------
        # Core components
        # --------------------------------------------------------

        self.memory = memory
        self.index = index
        self.tracer = tracer
        self.evaluator = evaluator
        self.llm = llm
        self.tools = tools or []

        # --------------------------------------------------------
        # ReAct components
        # --------------------------------------------------------

        self.formatter = ReActChatFormatter()
        self.output_parser = ReActOutputParser()

    # ============================================================
    # STEP 1
    # Prepare user request
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

        # --------------------------------------------------------
        # Store user message
        # --------------------------------------------------------

        self.memory.add(
            "user",
            query,
        )

        # --------------------------------------------------------
        # Trace request
        # --------------------------------------------------------

        self.tracer.log(
            "user_request",
            {
                "query": query,
            },
        )

        # --------------------------------------------------------
        # Build conversation
        # --------------------------------------------------------

        messages = [
            ChatMessage(
                role="system",
                content=(
                    "You are an AI healthcare scheduling assistant.\n\n"

                    "Your job is to help users find doctors and "
                    "schedule appointments.\n\n"

                    "Follow these rules:\n"
                    "1. Understand the user's healthcare scheduling "
                    "request.\n"
                    "2. Use the doctor search tool when you need to "
                    "find a suitable doctor.\n"
                    "3. Use the scheduling tool when the user has "
                    "provided the information required to schedule "
                    "an appointment.\n"
                    "4. Do not invent doctors or appointment details.\n"
                    "5. Do not claim that an appointment is confirmed "
                    "unless the scheduling tool provides confirmation.\n"
                    "6. If required information is missing, ask the "
                    "user for it.\n"
                    "7. Keep the final response clear and concise.\n"
                ),
            )
        ]

        # --------------------------------------------------------
        # Add conversation history
        # --------------------------------------------------------

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

        # --------------------------------------------------------
        # Store messages in workflow context
        # --------------------------------------------------------

        await ctx.set(
            "messages",
            messages,
        )

        # --------------------------------------------------------
        # Initialize reasoning history
        # --------------------------------------------------------

        await ctx.set(
            "reasoning_steps",
            [],
        )

        return PrepEvent()

    # ============================================================
    # STEP 2
    # Agent reasoning
    # ============================================================

    @step
    async def reasoning(
        self,
        ctx: Context,
        ev: PrepEvent,
    ):

        if self.llm is None:

            raise ValueError(
                "LLM has not been provided to "
                "SchedulingWorkflow."
            )

        # --------------------------------------------------------
        # Retrieve conversation
        # --------------------------------------------------------

        messages = await ctx.get(
            "messages",
            default=[],
        )

        # --------------------------------------------------------
        # Retrieve previous reasoning steps
        # --------------------------------------------------------

        reasoning_steps = await ctx.get(
            "reasoning_steps",
            default=[],
        )

        # --------------------------------------------------------
        # Format ReAct prompt
        # --------------------------------------------------------

        formatted_messages = self.formatter.format(
            self.tools,
            messages,
            reasoning_steps,
        )

        # --------------------------------------------------------
        # Call LLM
        # --------------------------------------------------------

        response = await self.llm.achat(
            formatted_messages
        )

        response_text = response.message.content

        # --------------------------------------------------------
        # Trace LLM response
        # --------------------------------------------------------

        self.tracer.log(
            "llm_response",
            {
                "response": response_text,
            },
        )

        # --------------------------------------------------------
        # Parse ReAct response
        # --------------------------------------------------------

        reasoning_step = self.output_parser.parse(
            response_text
        )

        # ========================================================
        # FINAL RESPONSE
        # ========================================================

        if not isinstance(
            reasoning_step,
            ActionReasoningStep,
        ):

            final_response = response_text

            # ----------------------------------------------------
            # Store assistant response
            # ----------------------------------------------------

            self.memory.add(
                "assistant",
                final_response,
            )

            # ----------------------------------------------------
            # Trace final response
            # ----------------------------------------------------

            self.tracer.log(
                "final_response",
                {
                    "response": final_response,
                },
            )

            # ----------------------------------------------------
            # Evaluation
            # ----------------------------------------------------

            if self.evaluator is not None:

                try:

                    self.evaluator.total_tasks += 1
                    self.evaluator.successful_tasks += 1

                except Exception:
                    pass

            return StopEvent(
                result={
                    "response": final_response,
                    "traces": self.tracer.get_traces(),
                }
            )

        # ========================================================
        # TOOL CALL
        # ========================================================

        # --------------------------------------------------------
        # Store reasoning step
        # --------------------------------------------------------

        reasoning_steps.append(
            reasoning_step
        )

        await ctx.set(
            "reasoning_steps",
            reasoning_steps,
        )

        # --------------------------------------------------------
        # Create tool selection
        # --------------------------------------------------------

        tool_call = ToolSelection(
            tool_id=reasoning_step.action,
            tool_name=reasoning_step.action,
            tool_kwargs=reasoning_step.action_input,
        )

        # --------------------------------------------------------
        # Trace tool selection
        # --------------------------------------------------------

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
    # STEP 3
    # Execute selected tool
    # ============================================================

    @step
    async def execute_tool(
        self,
        ctx: Context,
        ev: ToolCallEvent,
    ) -> ObservationEvent:

        tool_call = ev.tool_call

        # --------------------------------------------------------
        # Find requested tool
        # --------------------------------------------------------

        selected_tool = None

        for tool in self.tools:

            try:

                tool_name = tool.metadata.name

            except Exception:

                continue

            if tool_name == tool_call.tool_name:

                selected_tool = tool
                break

        # --------------------------------------------------------
        # Tool not found
        # --------------------------------------------------------

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

        # ========================================================
        # Execute tool
        # ========================================================

        try:

            result = await selected_tool.acall(
                **tool_call.tool_kwargs
            )

            observation = str(result)

            # ----------------------------------------------------
            # Trace successful tool execution
            # ----------------------------------------------------

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
    # STEP 4
    # Add tool observation and continue reasoning
    # ============================================================

    @step
    async def observe(
        self,
        ctx: Context,
        ev: ObservationEvent,
    ) -> PrepEvent:

        # --------------------------------------------------------
        # Retrieve reasoning history
        # --------------------------------------------------------

        reasoning_steps = await ctx.get(
            "reasoning_steps",
            default=[],
        )

        # --------------------------------------------------------
        # Add observation
        # --------------------------------------------------------

        reasoning_steps.append(
            ObservationReasoningStep(
                observation=ev.observation
            )
        )

        # --------------------------------------------------------
        # Store updated reasoning history
        # --------------------------------------------------------

        await ctx.set(
            "reasoning_steps",
            reasoning_steps,
        )

        # --------------------------------------------------------
        # Continue reasoning
        # --------------------------------------------------------

        return PrepEvent()