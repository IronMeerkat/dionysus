import logging

import socketio
from langchain_core.messages import AIMessage, AIMessageChunk, AnyMessage, HumanMessage, ToolMessage, ToolMessageChunk
from langchain_core.runnables import RunnableConfig

from agents.skilled_agent import spawn_skilled_agent
from hephaestus.langfuse_handler import langfuse_callback_handler

logger = logging.getLogger(__name__)

CAMPAIGN_NEGOTIATION_NS = "/campaign-negotiation"


def register_campaign_negotiation_events(sio: socketio.AsyncServer) -> None:
    """Register Socket.IO event handlers on the /campaign-negotiation namespace."""

    @sio.event(namespace=CAMPAIGN_NEGOTIATION_NS)
    async def connect(sid: str, environ: dict[str, object]) -> None:
        logger.info(f"🔌 [campaign-negotiation] Client connected: {sid}")

    @sio.event(namespace=CAMPAIGN_NEGOTIATION_NS)
    async def disconnect(sid: str) -> None:
        logger.info(f"🔌 [campaign-negotiation] Client disconnected: {sid}")

    @sio.event(namespace=CAMPAIGN_NEGOTIATION_NS)
    async def init_campaign_negotiation_session(sid: str, data: dict[str, object]) -> None:
        campaign_id = data.get("campaign_id")
        if campaign_id is None:
            await sio.emit(
                "error",
                {"message": "campaign_id is required."},
                to=sid,
                namespace=CAMPAIGN_NEGOTIATION_NS,
            )
            return

        try:
            campaign_id_int = int(campaign_id)
        except (TypeError, ValueError):
            logger.error(f"💥 [campaign-negotiation] Invalid campaign_id '{campaign_id}' from sid={sid}")
            await sio.emit(
                "error",
                {"message": "campaign_id must be an integer."},
                to=sid,
                namespace=CAMPAIGN_NEGOTIATION_NS,
            )
            return

        try:
            graph = spawn_skilled_agent(
                ["campaign-negotiation"],
                active=["campaign-negotiation"],
                campaign_id=campaign_id_int,
                name="campaign_negotiation",
            )
            await sio.save_session(sid, {
                "graph": graph,
                "campaign_id": campaign_id_int,
                "history": [],
            }, namespace=CAMPAIGN_NEGOTIATION_NS)

            logger.info(
                f"🤝 [campaign-negotiation] Session initialized for campaign {campaign_id_int} (sid={sid})"
            )
            await sio.emit(
                "campaign_negotiation_session_ready",
                {"campaign_id": campaign_id_int},
                to=sid,
                namespace=CAMPAIGN_NEGOTIATION_NS,
            )

        except Exception:
            logger.exception(f"💥 [campaign-negotiation] Failed to init session for sid={sid}")
            await sio.emit(
                "error",
                {"message": "Failed to initialise campaign negotiation session."},
                to=sid,
                namespace=CAMPAIGN_NEGOTIATION_NS,
            )

    @sio.event(namespace=CAMPAIGN_NEGOTIATION_NS)
    async def campaign_negotiation_message(sid: str, data: dict[str, object]) -> None:
        content = data.get("content", "")
        if not content:
            return

        logger.info(f"💬 [campaign-negotiation] message from {sid}: {str(content)[:120]}")

        sock_session = await sio.get_session(sid, namespace=CAMPAIGN_NEGOTIATION_NS)
        graph = sock_session.get("graph")
        history: list[AnyMessage] = sock_session.get("history", [])
        campaign_id: int = sock_session.get("campaign_id", 0)

        if graph is None:
            await sio.emit(
                "error",
                {"message": "No campaign negotiation session active. Call init_campaign_negotiation_session first."},
                to=sid,
                namespace=CAMPAIGN_NEGOTIATION_NS,
            )
            return

        human_msg = HumanMessage(content=str(content))
        history.append(human_msg)

        config = RunnableConfig(callbacks=[langfuse_callback_handler])
        collected_text = ""

        try:
            stream = graph.astream(
                {"messages": list(history)},
                stream_mode="messages",
                config=config,
                subgraphs=True,
            )

            async for item in stream:
                namespace_tuple, (msg, metadata) = item
                langgraph_node = metadata.get("langgraph_node", "")

                if isinstance(msg, AIMessageChunk) and langgraph_node in ("agent", "model"):
                    if msg.content:
                        token = str(msg.content)
                        collected_text += token
                        await sio.emit(
                            "campaign_negotiation_token",
                            {"token": token},
                            to=sid,
                            namespace=CAMPAIGN_NEGOTIATION_NS,
                        )

                elif isinstance(msg, (ToolMessage, ToolMessageChunk)):
                    tool_content = str(msg.content) if msg.content else ""
                    # Any tool that reports success changed campaign state; tell
                    # the UI so it can refresh its cached campaign view.
                    if tool_content.startswith("✅"):
                        await sio.emit(
                            "campaign_negotiation_updated",
                            {"summary": tool_content},
                            to=sid,
                            namespace=CAMPAIGN_NEGOTIATION_NS,
                        )
                        logger.info(
                            f"🤝 [campaign-negotiation] Emitted campaign_negotiation_updated: {tool_content[:80]}"
                        )

            if collected_text:
                history.append(AIMessage(content=collected_text))

            await sio.save_session(sid, {
                "graph": graph,
                "campaign_id": campaign_id,
                "history": history,
            }, namespace=CAMPAIGN_NEGOTIATION_NS)

        except Exception:
            logger.exception(f"💥 [campaign-negotiation] Stream error for sid={sid}")
            await sio.emit(
                "error",
                {"message": "An error occurred while processing your request."},
                to=sid,
                namespace=CAMPAIGN_NEGOTIATION_NS,
            )
        finally:
            await sio.emit("campaign_negotiation_done", {}, to=sid, namespace=CAMPAIGN_NEGOTIATION_NS)
            logger.debug(f"🏁 [campaign-negotiation] campaign_negotiation_done emitted for sid={sid}")
