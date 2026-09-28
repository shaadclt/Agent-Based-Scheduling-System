from time import time
from typing import Optional

from llama_index.core.agent.react import (
    ReActChatFormatter,
    ReActOutputParser,
)
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

from app.evaluation import AgentEvaluator
from app.memory import ConversationMemory
from app.traces import AgentTraceLogger


# ============================================================
# Workflow Events
# ============================================================

class PrepEvent(Event):
    """Prepare the next agent reasoning iteration."""
    pass


class InputEvent(Event):
    """Input prepared for the LLM."""

    input: list[ChatMessage]


class ToolCallEvent(Event):
    """Tool execution requested by the LLM."""

    tool_calls: list[ToolSelection]


# ============================================================
# Scheduling Workflow
# ============================================================

class SchedulingWorkflow(Workflow):
    """
    Event-driven healthcare scheduling agent using ReAct reasoning.

    Flow:

        StartEvent
            ↓
        PrepEvent
            ↓
        InputEvent
            ↓
        LLM reasoning
            ↓
        ┌───────────────┐
        │               │
        ▼               ▼
    ToolCallEvent    StopEvent
        │
        ▼
    Tool execution
        │
        └──────→ PrepEvent
    """

    def __init__(
        self,
        memory: ConversationMemory,
        tools: list,
        tracer: AgentTraceLogger,
        evaluator: Optional[AgentEvaluator] = None,
        llm=None,
        extra_context: str = "",
        timeout: int = 120,
    ):
        super().__init__(timeout=timeout)

        self.memory = memory
        self.tools = tools
        self.tracer = tracer
        self.evaluator = evaluator or AgentEvaluator()
        self.llm = llm

        self.formatter = ReActChatFormatter(
            context=extra_context
        )

        self.output_parser = ReActOutputParser()

        self.sources = []

    # ========================================================
    # Step 1 — Receive user request
    # ========================================================

    @step
    async def new_user_msg(
        self,
        ctx: Context,
        ev: StartEvent,
    ) -> PrepEvent:

        start_time = time()

        self.sources = []

        user_input = ev.input

        self.tracer.log(
            "request_received",
            user_input,
        )

        await ctx.set(
            "start_time",
            start_time,
        )

        await ctx.set(
            "current_reasoning",
            [],
        )

        self.memory.add(
            role="user",
            content=user_input,
        )

        return PrepEvent()

    # ========================================================
    # Step 2 — Prepare LLM input
    # ========================================================

    @step
    async def prepare_chat_history(
        self,
        ctx: Context,
        ev: PrepEvent,
    ) -> InputEvent:

        chat_history = self.memory.get()

        current_reasoning = await ctx.get(
            "current_reasoning",
            default=[],
        )

        llm_input = self.formatter.format(
            self.tools,
            chat_history,
            current_reasoning=current_reasoning,
        )

        self.tracer.log(
            "prepare_llm_input",
            f"Prepared {len(chat_history)} chat messages.",
        )

        return InputEvent(
            input=llm_input,
        )

    # ========================================================
    # Step 3 — LLM reasoning
    # ========================================================

    @step
    async def handle_llm_input(
        self,
        ctx: Context,
        ev: InputEvent,
    ) -> ToolCallEvent | StopEvent:

        response = await self.llm.achat(
            ev.input
        )

        raw_response = response.message.content

        self.tracer.log(
            "llm_response",
            str(raw_response),
        )

        try:

            reasoning_step = self.output_parser.parse(
                raw_response
            )

            current_reasoning = await ctx.get(
                "current_reasoning",
                default=[],
            )

            current_reasoning.append(
                reasoning_step
            )

            # ------------------------------------------------
            # Final answer
            # ------------------------------------------------

            if reasoning_step.is_done:

                final_response = reasoning_step.response

                self.memory.add(
                    role="assistant",
                    content=final_response,
                )

                start_time = await ctx.get(
                    "start_time",
                    default=time(),
                )

                latency = time() - start_time

                self.evaluator.log_latency(
                    latency
                )

                self.evaluator.log_task(
                    bool(final_response)
                )

                self.tracer.log(
                    "agent_completed",
                    f"Completed in {latency:.2f}s",
                )

                return StopEvent(
                    result={
                        "response": final_response,
                        "sources": self.sources,
                        "reasoning": current_reasoning,
                        "evaluation": self.evaluator.report(),
                    }
                )

            # ------------------------------------------------
            # Tool call
            # ------------------------------------------------

            if isinstance(
                reasoning_step,
                ActionReasoningStep,
            ):

                tool_name = reasoning_step.action
                tool_args = reasoning_step.action_input

                self.tracer.log(
                    "tool_selected",
                    f"{tool_name}({tool_args})",
                )

                return ToolCallEvent(
                    tool_calls=[
                        ToolSelection(
                            tool_id="agent_tool_call",
                            tool_name=tool_name,
                            tool_kwargs=tool_args,
                        )
                    ]
                )

        except Exception as exc:

            current_reasoning = await ctx.get(
                "current_reasoning",
                default=[],
            )

            current_reasoning.append(
                ObservationReasoningStep(
                    observation=(
                        "Error parsing LLM reasoning: "
                        f"{exc}"
                    )
                )
            )

            self.tracer.log(
                "reasoning_error",
                str(exc),
            )

        return PrepEvent()

    # ========================================================
    # Step 4 — Execute tools
    # ========================================================

    @step
    async def handle_tool_calls(
        self,
        ctx: Context,
        ev: ToolCallEvent,
    ) -> PrepEvent:

        current_reasoning = await ctx.get(
            "current_reasoning",
            default=[],
        )

        tools_by_name = {
            tool.metadata.get_name(): tool
            for tool in self.tools
        }

        for tool_call in ev.tool_calls:

            tool_name = tool_call.tool_name

            tool = tools_by_name.get(
                tool_name
            )

            # ------------------------------------------------
            # Invalid tool
            # ------------------------------------------------

            if tool is None:

                message = (
                    f"Tool '{tool_name}' does not exist."
                )

                self.tracer.log(
                    "invalid_tool",
                    message,
                )

                self.evaluator.log_invalid_action()

                current_reasoning.append(
                    ObservationReasoningStep(
                        observation=message
                    )
                )

                continue

            # ------------------------------------------------
            # Execute tool
            # ------------------------------------------------

            try:

                self.tracer.log(
                    "tool_execution",
                    f"Executing {tool_name}",
                )

                tool_output = tool(
                    **tool_call.tool_kwargs
                )

                output_content = (
                    tool_output.content
                    if hasattr(
                        tool_output,
                        "content",
                    )
                    else str(tool_output)
                )

                self.sources.append(
                    tool_output
                )

                current_reasoning.append(
                    ObservationReasoningStep(
                        observation=output_content
                    )
                )

                self.tracer.log(
                    "tool_result",
                    output_content,
                )

            except Exception as exc:

                message = (
                    f"Error executing "
                    f"{tool_name}: {exc}"
                )

                self.tracer.log(
                    "tool_error",
                    message,
                )

                current_reasoning.append(
                    ObservationReasoningStep(
                        observation=message
                    )
                )

        return PrepEvent()