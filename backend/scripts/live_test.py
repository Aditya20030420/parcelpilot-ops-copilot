"""Live end-to-end test of the agent loop against the real data pack + OpenAI."""
import asyncio
import sys

from app.agent.loop import AgentRunner
from app.auth import resolve_user
from app.core.knowledge import knowledge
from app.core.session import store
from app.tools.context import ToolContext

knowledge.load()


async def ask(token, text, session_id):
    sess = store.get_or_create(session_id)
    ctx = ToolContext(user=resolve_user(token), session_id=sess.session_id,
                      knowledge=knowledge, store=store)
    runner = AgentRunner(ctx, sess)
    pending_action = None
    async for ev in runner.run(text):
        t = ev["type"]
        if t == "tool_call":
            print(f"    [tool] {ev['name']}({ev['args']})")
        elif t == "tool_result":
            print(f"    [ ok ] {ev['name']} -> {ev['summary']}")
        elif t == "confirmation_required":
            print(f"    [CONFIRM?] {ev['tool_name']}: {ev['summary']}")
            pending_action = ev["action_id"]
        elif t == "assistant_text":
            print(f"  GPT> {ev['text']}")
        elif t == "error":
            print(f"    [ERROR] {ev['message']}")
    return sess.session_id, pending_action


async def confirm(token, session_id, action_id):
    from app.main import _ACTION_PERM
    from app.tools.registry import execute_action
    sess = store.get_or_create(session_id)
    ctx = ToolContext(user=resolve_user(token), session_id=sess.session_id,
                      knowledge=knowledge, store=store)
    action = store.get_pending(action_id)
    result = execute_action(ctx, action)
    action.status = "confirmed"
    print(f"    [EXECUTED] {result}")
    runner = AgentRunner(ctx, sess)
    async for ev in runner.run(f"[SYSTEM] User CONFIRMED '{action.tool_name}'. Result: {result}. "
                               f"Acknowledge briefly."):
        if ev["type"] == "assistant_text":
            print(f"  GPT> {ev['text']}")


async def main():
    print("\n===== 1) Northstar cancellation (multi-step) =====")
    await ask("token-agent",
              "Can Northstar cancel ORD-1001 without a cancellation fee? Explain why.", "s1")

    print("\n===== 2) Service credit for carrier-fault order ORD-2002 =====")
    await ask("token-agent",
              "ORD-2002 missed pickup due to carrier fault. Is a service credit owed and how much?",
              "s2")

    print("\n===== 3) Historical-resolution trap (TKT-450) =====")
    await ask("token-agent",
              "For TKT-450, was the historical resolution correct? What should we tell the customer?",
              "s3")

    print("\n===== 4) Proactive scan =====")
    await ask("token-manager", "Scan our support activity for anything urgent or unusual.", "s4")

    print("\n===== 5) Access control: analyst tries to escalate =====")
    await ask("token-analyst",
              "Escalate the security issue on TKT-505 to the security team urgently.", "s5")

    print("\n===== 6) Agent escalates TKT-505 (with confirmation) =====")
    sid, action_id = await ask(
        "token-agent",
        "Escalate the security issue on TKT-505 to the security team urgently.", "s6")
    if action_id:
        print("  -- user clicks Confirm --")
        await confirm("token-agent", sid, action_id)
    else:
        print("  (no confirmation was requested)")


if __name__ == "__main__":
    asyncio.run(main())
