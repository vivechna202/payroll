"""
workflow_service.py – Reusable workflow approval engine.
Manages workflow_requests.csv and workflow_history.csv.
"""

import os
import uuid
import json
import pandas as pd
from datetime import datetime
from app.base.utils.config import DUMMY_DATA_FOLDER
from app.base.utils.csv_service import read_csv, write_csv, append_row
from app.workflow.services.notification_service import create_notification

CSV_WORKFLOW_REQUESTS = os.path.join(DUMMY_DATA_FOLDER, "workflow_requests.csv")
CSV_WORKFLOW_HISTORY = os.path.join(DUMMY_DATA_FOLDER, "workflow_history.csv")

def ensure_workflow_csvs():
    """Ensure the workflow CSV files exist with correct columns."""
    if not os.path.exists(CSV_WORKFLOW_REQUESTS):
        os.makedirs(os.path.dirname(CSV_WORKFLOW_REQUESTS), exist_ok=True)
        pd.DataFrame(columns=[
            "request_id", "module", "record_id", "employee_id", "title",
            "description", "status", "current_step", "total_steps",
            "steps_json", "created_by", "created_at", "updated_at"
        ]).to_csv(CSV_WORKFLOW_REQUESTS, index=False)
        
    if not os.path.exists(CSV_WORKFLOW_HISTORY):
        os.makedirs(os.path.dirname(CSV_WORKFLOW_HISTORY), exist_ok=True)
        pd.DataFrame(columns=[
            "history_id", "request_id", "step_num", "action",
            "action_by", "action_at", "comment"
        ]).to_csv(CSV_WORKFLOW_HISTORY, index=False)

def create_workflow_request(module: str, record_id: str, employee_id: str, title: str, description: str, steps: list, created_by: str) -> dict:
    """
    Initiate a new workflow request.
    steps is a list of dicts: [{"step_num": 1, "approver": "EMP003", "status": "Pending"}]
    approver can be employee_id, "hr", or "manager".
    """
    ensure_workflow_csvs()
    req_id = f"WFR-{str(uuid.uuid4())[:8].upper()}"
    
    # Initialize first step status
    for s in steps:
        if s["step_num"] == 1:
            s["status"] = "Pending Approval"
        else:
            s["status"] = "Draft"
            
    request_record = {
        "request_id": req_id,
        "module": module,
        "record_id": record_id,
        "employee_id": employee_id,
        "title": title,
        "description": description,
        "status": "Submitted",
        "current_step": 1,
        "total_steps": len(steps),
        "steps_json": json.dumps(steps),
        "created_by": created_by,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat()
    }
    
    append_row(CSV_WORKFLOW_REQUESTS, request_record)
    
    # Audit log
    log_workflow_action(req_id, 0, "Submitted", created_by, "Workflow request initiated.")
    
    # Notify first approver
    first_approver = steps[0]["approver"]
    create_notification(
        recipient_id=first_approver,
        message=f"New approval request: {title} from {created_by}",
        notification_type="Reminder",
        link=f"/hr/workflow/view/{req_id}"
    )
    
    return request_record

def log_workflow_action(request_id: str, step_num: int, action: str, action_by: str, comment: str):
    """Log workflow history audit trail."""
    ensure_workflow_csvs()
    history_record = {
        "history_id": f"WFH-{str(uuid.uuid4())[:8].upper()}",
        "request_id": request_id,
        "step_num": step_num,
        "action": action,
        "action_by": action_by,
        "action_at": datetime.now().isoformat(),
        "comment": comment
    }
    append_row(CSV_WORKFLOW_HISTORY, history_record)

def get_workflow_request(request_id: str) -> dict or None:
    """Retrieve detailed workflow request."""
    ensure_workflow_csvs()
    df = read_csv(CSV_WORKFLOW_REQUESTS)
    if df.empty or "request_id" not in df.columns:
        return None
        
    res = df[df["request_id"] == request_id]
    if res.empty:
        return None
        
    return res.iloc[0].to_dict()

def get_workflow_history(request_id: str) -> list[dict]:
    """Retrieve approval history timeline."""
    ensure_workflow_csvs()
    df = read_csv(CSV_WORKFLOW_HISTORY)
    if df.empty or "request_id" not in df.columns:
        return []
        
    res = df[df["request_id"] == request_id]
    if res.empty:
        return []
        
    # Sort by action_at ascending
    if "action_at" in res.columns:
        res = res.sort_values(by="action_at", ascending=True)
        
    return res.to_dict(orient="records")

def get_all_workflow_requests() -> list[dict]:
    """Get all requests."""
    ensure_workflow_csvs()
    df = read_csv(CSV_WORKFLOW_REQUESTS)
    if df.empty:
        return []
    return df.to_dict(orient="records")

def get_pending_approvals(approver_id: str) -> list[dict]:
    """Get all requests currently pending approval by this approver or role."""
    ensure_workflow_csvs()
    df = read_csv(CSV_WORKFLOW_REQUESTS)
    if df.empty:
        return []
        
    pending = []
    for _, row in df.iterrows():
        # Only process active pending requests
        if row["status"] not in ["Submitted", "Pending Approval"]:
            continue
            
        steps = json.loads(row["steps_json"])
        current_step_num = int(row["current_step"])
        
        # Check current step details
        for s in steps:
            if s["step_num"] == current_step_num:
                # Matches if the approver_id matches specifically, or if they have the 'hr' role
                if s["approver"] == approver_id or (s["approver"] == "hr" and approver_id == "hr"):
                    pending.append(row.to_dict())
                    break
                    
    return pending

def process_approval(request_id: str, approver_id: str, action: str, comment: str) -> dict:
    """
    Approve, Reject, or Send Back a workflow request.
    action can be: 'Approve', 'Reject', 'Send Back'
    """
    ensure_workflow_csvs()
    df = read_csv(CSV_WORKFLOW_REQUESTS)
    if df.empty or "request_id" not in df.columns:
        return {"status": "error", "message": "Request not found."}
        
    mask = df["request_id"] == request_id
    if not mask.any():
        return {"status": "error", "message": "Request not found."}
        
    idx = df.index[mask][0]
    row = df.iloc[idx].to_dict()
    
    steps = json.loads(row["steps_json"])
    current_step_num = int(row["current_step"])
    total_steps = int(row["total_steps"])
    
    # Find current step details
    current_step = None
    for s in steps:
        if s["step_num"] == current_step_num:
            current_step = s
            break
            
    if not current_step:
        return {"status": "error", "message": "Invalid current step."}
        
    # Verify authorization
    if current_step["approver"] != approver_id and not (current_step["approver"] == "hr" and approver_id == "hr"):
        return {"status": "error", "message": "Unauthorized action."}
        
    # Perform action
    if action == "Approve":
        current_step["status"] = "Approved"
        log_workflow_action(request_id, current_step_num, "Approved", approver_id, comment)
        create_notification(
            recipient_id=row["employee_id"],
            message=f"Your request '{row['title']}' was approved at step {current_step_num}.",
            notification_type="Success"
        )
        
        # Advance step or complete
        if current_step_num < total_steps:
            next_step_num = current_step_num + 1
            df.at[idx, "current_step"] = next_step_num
            df.at[idx, "status"] = "Pending Approval"
            
            # Update next step status
            for s in steps:
                if s["step_num"] == next_step_num:
                    s["status"] = "Pending Approval"
                    # Notify next approver
                    create_notification(
                        recipient_id=s["approver"],
                        message=f"Approval needed: {row['title']}",
                        notification_type="Reminder",
                        link=f"/hr/workflow/view/{request_id}"
                    )
                    break
        else:
            df.at[idx, "status"] = "Completed"
            # Final completion integration: execute the specific target action
            execute_completed_action(row["module"], row["record_id"])
            create_notification(
                recipient_id=row["employee_id"],
                message=f"Congratulations! Your request '{row['title']}' has been fully approved & completed.",
                notification_type="Success"
            )
            
    elif action == "Reject":
        current_step["status"] = "Rejected"
        df.at[idx, "status"] = "Rejected"
        log_workflow_action(request_id, current_step_num, "Rejected", approver_id, comment)
        create_notification(
            recipient_id=row["employee_id"],
            message=f"Sorry, your request '{row['title']}' was rejected by {approver_id}.",
            notification_type="Warning"
        )
        
    elif action == "Send Back":
        current_step["status"] = "Draft"
        if current_step_num > 1:
            prev_step_num = current_step_num - 1
            df.at[idx, "current_step"] = prev_step_num
            df.at[idx, "status"] = "Pending Approval"
            for s in steps:
                if s["step_num"] == prev_step_num:
                    s["status"] = "Pending Approval"
                    create_notification(
                        recipient_id=s["approver"],
                        message=f"Request sent back to you: {row['title']}",
                        notification_type="Warning",
                        link=f"/hr/workflow/view/{request_id}"
                    )
                    break
        else:
            # Send back to creator
            df.at[idx, "status"] = "Draft"
            df.at[idx, "current_step"] = 1
            create_notification(
                recipient_id=row["employee_id"],
                message=f"Your request '{row['title']}' was sent back by the approver. Please review comments.",
                notification_type="Warning"
            )
            
        log_workflow_action(request_id, current_step_num, "Sent Back", approver_id, comment)
        
    df.at[idx, "steps_json"] = json.dumps(steps)
    df.at[idx, "updated_at"] = datetime.now().isoformat()
    write_csv(CSV_WORKFLOW_REQUESTS, df)
    return {"status": "success", "message": f"Request {action}d successfully."}

def cancel_workflow_request(request_id: str, employee_id: str) -> dict:
    """Cancel a draft or submitted workflow request."""
    ensure_workflow_csvs()
    df = read_csv(CSV_WORKFLOW_REQUESTS)
    if df.empty or "request_id" not in df.columns:
        return {"status": "error", "message": "Request not found."}
        
    mask = df["request_id"] == request_id
    if not mask.any():
        return {"status": "error", "message": "Request not found."}
        
    idx = df.index[mask][0]
    row = df.iloc[idx].to_dict()
    
    # Check permissions
    if row["employee_id"] != employee_id and employee_id != "hr":
        return {"status": "error", "message": "Unauthorized action."}
        
    if row["status"] in ["Approved", "Completed", "Rejected"]:
        return {"status": "error", "message": "Cannot cancel completed or approved requests."}
        
    df.at[idx, "status"] = "Cancelled"
    df.at[idx, "updated_at"] = datetime.now().isoformat()
    write_csv(CSV_WORKFLOW_REQUESTS, df)
    
    log_workflow_action(request_id, int(row["current_step"]), "Cancelled", employee_id, "Workflow request cancelled.")
    return {"status": "success", "message": "Request cancelled successfully."}

def execute_completed_action(module: str, record_id: str):
    """Integrate with source modules when approval is fully completed."""
    if module == "Contracts":
        # Approve contract
        from app.payroll.services.contract_service import update_contract_status
        # In a real setup, we update the status, let's call the update status function
        pass
    elif module == "Full & Final Settlement":
        # Approve FNF settlement
        from app.payroll.services.fnf_service import update_settlement_status
        # update_settlement_status(record_id, "Approved", "System")
        pass
    elif module == "Investment Proofs":
        # Verify proof
        from app.taxation.services.proof_service import approve_proof
        # approve_proof(record_id, "System")
        pass
