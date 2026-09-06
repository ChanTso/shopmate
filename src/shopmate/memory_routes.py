"""Authenticated memory editing; model extraction never supplies the owner or role."""

from typing import Annotated

from commerce_common.memory import MemoryWriteRejected
from fastapi import Body, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .auth import bind_context


class EditMemory(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1, max_length=64)
    value: str = Field(min_length=1, max_length=200)


class DeleteMemory(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1, max_length=64)


def install_memory_routes(app, prefix, dependency, resources, role):
    @app.get(prefix + "/memory")
    async def read_memory(bound=dependency):
        user, record = bound
        subject = user.subject if role == "buyer" else "citybuddy"
        with bind_context(user, record.session_id, role=role):
            facts = await resources["memory"].get_facts(subject)
        return {"facts": [fact.model_dump(mode="json") for fact in facts]}

    @app.patch(prefix + "/memory")
    async def edit_memory(request: EditMemory, bound=dependency):
        user, record = bound
        subject = user.subject if role == "buyer" else "citybuddy"
        agent = resources["buyer_agent" if role == "buyer" else "agent"]
        with bind_context(user, record.session_id, role=role):
            old = next(
                (f for f in await resources["memory"].get_facts(subject) if f.key == request.key),
                None,
            )
            if old is None:
                raise HTTPException(404, "Memory fact not found")
            try:
                fact = agent.memory.validate(
                    request.key,
                    request.value,
                    old.category.value,
                    source_session_id=old.source_session_id,
                )
            except MemoryWriteRejected as error:
                raise HTTPException(400, str(error)) from None
            await resources["memory"].upsert_facts(subject, [fact])
        return {"fact": fact.model_dump(mode="json")}

    @app.delete(prefix + "/memory")
    async def delete_memory(
        request: Annotated[DeleteMemory | None, Body()] = None, bound=dependency
    ):
        user, record = bound
        subject = user.subject if role == "buyer" else "citybuddy"
        with bind_context(user, record.session_id, role=role):
            if request is None:
                await resources["memory"].clear(subject)
            else:
                await resources["memory"].delete_fact(subject, request.key)
        return {"deleted": True}
