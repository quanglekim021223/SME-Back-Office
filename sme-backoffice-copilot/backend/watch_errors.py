import asyncio
import sys
from uuid import UUID
from datetime import datetime, timezone
from sqlalchemy import select
from app.core.db import async_session_factory
from app.models import Document, WorkflowRun, AgentStepExecution

async def main():
    print("Starting DB error watcher...")
    seen_step_ids = set()
    seen_workflow_ids = set()
    
    while True:
        try:
            async with async_session_factory() as session:
                # Watch AgentStepExecutions
                stmt = select(AgentStepExecution).order_by(AgentStepExecution.created_at.desc()).limit(10)
                res = await session.execute(stmt)
                steps = res.scalars().all()
                for step in steps:
                    if step.id not in seen_step_ids:
                        seen_step_ids.add(step.id)
                        if step.status == "failed":
                            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Agent Step Failed!")
                            print(f"  Agent: {step.agent_name}")
                            print(f"  Status: {step.status}")
                            print(f"  Error Code: {step.error_code}")
                            print(f"  Error Message: {step.error_message}")
                
                # Watch WorkflowRuns
                stmt_wf = select(WorkflowRun).order_by(WorkflowRun.created_at.desc()).limit(10)
                res_wf = await session.execute(stmt_wf)
                wfs = res_wf.scalars().all()
                for wf in wfs:
                    if wf.id not in seen_workflow_ids:
                        seen_workflow_ids.add(wf.id)
                        if wf.state.get("status") == "failed":
                            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Workflow Failed!")
                            print(f"  Workflow Run ID: {wf.id}")
                            print(f"  Document ID: {wf.document_id}")
                            print(f"  State: {wf.state}")
                            
        except Exception as e:
            print("Watcher Error:", e)
            
        await asyncio.sleep(0.5)

if __name__ == "__main__":
    asyncio.run(main())
